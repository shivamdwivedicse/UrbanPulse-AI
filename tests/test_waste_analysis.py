"""Tests for waste image validation and Gemini response handling."""

import asyncio
import logging
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.genai import errors
from PIL import Image

from backend.main import app
from backend.schemas.waste_analysis import WasteAnalysisResponse
from backend.services import gemini_waste_service
from backend.services.gemini_waste_service import (
    GeminiWasteAnalysisService,
    get_waste_analysis_service,
    validate_image,
)


def create_image(image_format: str = "PNG", size: tuple[int, int] = (20, 10)) -> bytes:
    image = Image.new("RGB", size, color="green")
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def make_result(**overrides) -> WasteAnalysisResponse:
    values = {
        "category": "Plastic",
        "accumulation_assessment": "Moderate",
        "overflow_assessment": "Not Visible",
        "severity": "MEDIUM",
        "explanation": "Several plastic containers are visible in the image.",
        "recommended_action": "Separate the visible containers for recycling.",
        "is_uncertain": False,
        "uncertainty_reason": None,
    }
    values.update(overrides)
    return WasteAnalysisResponse(**values)


def schema_contains_key(value, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(schema_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(schema_contains_key(item, key) for item in value)
    return False


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None, **_kwargs):
        self.models = FakeModels(response=response, error=error)
        self.init_kwargs = _kwargs
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def client():
    async def fake_analyze(_image_bytes, _mime_type):
        return make_result()

    class FakeService:
        analyze_image = staticmethod(fake_analyze)

    app.dependency_overrides[get_waste_analysis_service] = lambda: FakeService()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_waste_analysis_service, None)


def test_schema_rejects_missing_uncertainty_reason():
    with pytest.raises(ValueError, match="uncertainty_reason is required"):
        make_result(is_uncertain=True)


def test_schema_allows_explicit_unassessable_result():
    result = make_result(
        category="Unknown",
        accumulation_assessment="Not assessable",
        overflow_assessment=None,
        severity=None,
        explanation="The image does not show enough detail to identify waste.",
        recommended_action="Upload a clearer image showing the waste.",
        is_uncertain=True,
        uncertainty_reason="The image is too unclear to assess.",
    )
    assert result.category == "Unknown"
    assert result.severity is None


@pytest.mark.parametrize(
    ("image_format", "mime_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_validate_accepts_supported_image_formats(image_format, mime_type):
    validate_image(create_image(image_format), mime_type)


def test_validate_rejects_mime_content_mismatch():
    with pytest.raises(HTTPException) as exc_info:
        validate_image(create_image("PNG"), "image/jpeg")
    assert exc_info.value.status_code == 415


def test_validate_rejects_corrupt_image():
    with pytest.raises(HTTPException) as exc_info:
        validate_image(b"not an image", "image/png")
    assert exc_info.value.status_code == 422


def test_validate_rejects_excessive_dimensions():
    with pytest.raises(HTTPException) as exc_info:
        validate_image(create_image("PNG", (10_001, 1)), "image/png")
    assert exc_info.value.status_code == 413


def test_validate_rejects_excessive_pixel_count(monkeypatch):
    class OversizedImageHeader:
        format = "PNG"
        size = (8_000, 6_000)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(gemini_waste_service.Image, "open", lambda *_args, **_kwargs: OversizedImageHeader())
    with pytest.raises(HTTPException) as exc_info:
        validate_image(b"mocked header", "image/png")
    assert exc_info.value.status_code == 413


def test_endpoint_returns_structured_analysis(client):
    response = client.post(
        "/api/v1/waste/analyze",
        files={"image": ("waste.png", create_image(), "image/png")},
    )
    assert response.status_code == 200
    assert response.json() == make_result().model_dump()


def test_endpoint_rejects_unsupported_mime(client):
    response = client.post(
        "/api/v1/waste/analyze",
        files={"image": ("waste.gif", create_image(), "image/gif")},
    )
    assert response.status_code == 415


def test_endpoint_rejects_oversized_upload(client):
    response = client.post(
        "/api/v1/waste/analyze",
        files={"image": ("large.png", b"x" * (8 * 1024 * 1024 + 1), "image/png")},
    )
    assert response.status_code == 413


def test_endpoint_rejects_mime_content_mismatch(client):
    response = client.post(
        "/api/v1/waste/analyze",
        files={"image": ("waste.jpg", create_image("PNG"), "image/jpeg")},
    )
    assert response.status_code == 415


def test_service_passes_image_and_schema_to_gemini():
    response = SimpleNamespace(parsed=make_result(), text=None)
    image_bytes = create_image()
    created_clients = []

    def factory(**kwargs):
        fake = FakeClient(response=response, **kwargs)
        created_clients.append(fake)
        return fake

    service = GeminiWasteAnalysisService(api_key="test-key", client_factory=factory)
    result = asyncio.run(service.analyze_image(image_bytes, "image/png"))

    assert result == make_result()
    assert created_clients[0].closed is True
    http_options = created_clients[0].init_kwargs["http_options"]
    assert http_options.timeout == 60_000
    assert http_options.retry_options.attempts == 1
    call = created_clients[0].models.calls[0]
    assert call["model"] == "gemini-3.8-flash"
    assert call["config"].temperature is None
    schema = WasteAnalysisResponse.model_json_schema()
    gemini_waste_service._remove_additional_properties(schema)
    assert call["config"].response_schema == schema
    assert not schema_contains_key(call["config"].response_schema, "additionalProperties")
    assert call["contents"][1].inline_data.mime_type == "image/png"
    assert call["contents"][1].inline_data.data == image_bytes


def test_service_removes_additional_properties_recursively_from_schema():
    schema = {
        "additionalProperties": False,
        "properties": {
            "nested": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "items": [
                        {"additionalProperties": False, "type": "string"}
                    ]
                },
            }
        },
    }

    gemini_waste_service._remove_additional_properties(schema)

    assert schema == {
        "properties": {
            "nested": {
                "type": "object",
                "properties": {"items": [{"type": "string"}]},
            }
        }
    }


def test_service_converts_valid_gemini_json_to_response():
    response = SimpleNamespace(parsed=None, text=make_result().model_dump_json())
    service = GeminiWasteAnalysisService(
        api_key="test-key",
        client_factory=lambda **kwargs: FakeClient(response=response, **kwargs),
    )

    result = asyncio.run(service.analyze_image(create_image(), "image/png"))

    assert isinstance(result, WasteAnalysisResponse)
    assert result == make_result()


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "unverified"},
        {"severity": "CRITICAL"},
    ],
)
def test_service_rejects_invalid_gemini_enum_values(overrides):
    invalid_result = make_result().model_dump()
    invalid_result.update(overrides)
    response = SimpleNamespace(parsed=invalid_result, text=None)
    service = GeminiWasteAnalysisService(
        api_key="test-key",
        client_factory=lambda **kwargs: FakeClient(response=response, **kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.analyze_image(create_image(), "image/png"))

    assert exc_info.value.status_code == 502


def test_service_handles_malformed_gemini_json_safely():
    response = SimpleNamespace(parsed=None, text='{"category":')
    service = GeminiWasteAnalysisService(
        api_key="test-key",
        client_factory=lambda **kwargs: FakeClient(response=response, **kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.analyze_image(create_image(), "image/png"))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Gemini returned an invalid analysis response."


def test_service_maps_quota_error():
    service = GeminiWasteAnalysisService(
        api_key="test-key",
        client_factory=lambda **kwargs: FakeClient(
            error=errors.APIError(code=429, response_json={"error": {"message": "quota"}}),
            **kwargs,
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.analyze_image(create_image(), "image/png"))
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == gemini_waste_service.TEMPORARILY_BUSY_MESSAGE
    assert exc_info.value.headers == {
        "Retry-After": str(gemini_waste_service.OVERLOAD_RETRY_AFTER_SECONDS)
    }


@pytest.mark.parametrize(
    ("provider_status", "provider_message"),
    [
        (503, "service unavailable"),
        (500, "This model is currently experiencing high demand. Please try again later."),
        (500, "The model is temporarily overloaded."),
    ],
)
def test_service_maps_provider_overload_to_retryable_503(provider_status, provider_message):
    service = GeminiWasteAnalysisService(
        api_key="test-key",
        client_factory=lambda **kwargs: FakeClient(
            error=errors.APIError(
                code=provider_status,
                response_json={"error": {"message": provider_message}},
            ),
            **kwargs,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.analyze_image(create_image(), "image/png"))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == gemini_waste_service.TEMPORARILY_BUSY_MESSAGE
    assert exc_info.value.headers == {
        "Retry-After": str(gemini_waste_service.OVERLOAD_RETRY_AFTER_SECONDS)
    }


def test_service_maps_provider_bad_request_and_logs_sanitized_detail(caplog):
    api_key = "AIza123456789012345678901234567890123"
    service = GeminiWasteAnalysisService(
        api_key=api_key,
        client_factory=lambda **kwargs: FakeClient(
            error=errors.APIError(
                code=400,
                response_json={
                    "error": {
                        "message": f"Invalid schema; api_key={api_key}",
                    }
                },
            ),
            **kwargs,
        ),
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(service.analyze_image(create_image(), "image/png"))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Gemini could not analyze the image. Please try again later."
    provider_record = next(
        record for record in caplog.records if record.event == "gemini_provider_request_failed"
    )
    assert provider_record.provider_status == 400
    assert provider_record.exception_type == "APIError"
    assert provider_record.elapsed_ms >= 0
    assert "APIError" not in caplog.text
    assert "Invalid schema" in caplog.text
    assert api_key not in caplog.text
    assert "[REDACTED]" in caplog.text


@pytest.mark.parametrize(
    ("provider_status", "provider_message"),
    [
        (401, "Unauthenticated"),
        (403, "Permission denied"),
        (400, "API_KEY_INVALID: API key not valid"),
    ],
)
def test_service_maps_invalid_api_key_to_configuration_error(
    provider_status, provider_message, caplog
):
    api_key = "AIza123456789012345678901234567890123"
    service = GeminiWasteAnalysisService(
        api_key=api_key,
        client_factory=lambda **kwargs: FakeClient(
            error=errors.APIError(
                code=provider_status,
                response_json={"error": {"message": provider_message}},
            ),
            **kwargs,
        ),
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(service.analyze_image(create_image(), "image/png"))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == gemini_waste_service.CONFIGURATION_ERROR_MESSAGE
    record = next(record for record in caplog.records if record.event == "gemini_authentication_failed")
    assert record.provider_status == provider_status
    assert record.elapsed_ms >= 0
    assert provider_message in caplog.text
    assert api_key not in caplog.text


@pytest.mark.parametrize(
    ("provider_status", "provider_message"),
    [
        (404, "models/gemini-invalid was not found"),
        (400, "Invalid model name supplied"),
    ],
)
def test_service_maps_invalid_model_to_clear_upstream_error(
    provider_status, provider_message, caplog
):
    service = GeminiWasteAnalysisService(
        api_key="test-key",
        client_factory=lambda **kwargs: FakeClient(
            error=errors.APIError(
                code=provider_status,
                response_json={"error": {"message": provider_message}},
            ),
            **kwargs,
        ),
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(service.analyze_image(create_image(), "image/png"))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == gemini_waste_service.INVALID_MODEL_MESSAGE
    record = next(record for record in caplog.records if record.event == "gemini_model_invalid")
    assert record.provider_status == provider_status
    assert record.elapsed_ms >= 0
    assert provider_message in caplog.text


@pytest.mark.parametrize(
    ("error", "timeout_source", "provider_status"),
    [
        (httpx.TimeoutException("transport timeout"), "http_transport", None),
        (TimeoutError("SDK timeout"), "sdk_timeout", None),
        (
            errors.APIError(code=408, response_json={"error": {"message": "provider timeout"}}),
            "provider_http_408",
            408,
        ),
        (
            errors.APIError(code=504, response_json={"error": {"message": "provider timeout"}}),
            "provider_http_504",
            504,
        ),
    ],
)
def test_service_maps_timeout_sources_and_logs_safely(
    error, timeout_source, provider_status, caplog
):
    service = GeminiWasteAnalysisService(
        api_key="test-key",
        client_factory=lambda **kwargs: FakeClient(error=error, **kwargs),
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(service.analyze_image(create_image(), "image/png"))

    assert exc_info.value.status_code == 504
    timeout_record = next(
        record for record in caplog.records if record.event == "gemini_request_timeout"
    )
    assert timeout_record.timeout_source == timeout_source
    assert timeout_record.exception_type == type(error).__name__
    assert timeout_record.provider_status == provider_status
    assert timeout_record.elapsed_ms >= 0
    assert "image" not in timeout_record.getMessage().lower()


def test_service_maps_invalid_structured_response():
    service = GeminiWasteAnalysisService(
        api_key="test-key",
        client_factory=lambda **kwargs: FakeClient(
            response=SimpleNamespace(parsed={"category": "unverified", "extra_claim": "unknown"}, text=None),
            **kwargs,
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.analyze_image(create_image(), "image/png"))
    assert exc_info.value.status_code == 502


def test_service_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    service = GeminiWasteAnalysisService(client_factory=lambda **_kwargs: pytest.fail("client must not be created"))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.analyze_image(create_image(), "image/png"))
    assert exc_info.value.status_code == 503


def test_waste_route_is_registered():
    assert "/api/v1/waste/analyze" in app.openapi()["paths"]
