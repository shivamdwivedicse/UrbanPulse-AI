"""Gemini-backed waste image analysis."""

import asyncio
import logging
import os
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException, status
from google import genai
from google.genai import errors, types
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from backend.schemas.waste_analysis import WasteAnalysisResponse


logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_DIMENSION = 10_000
MAX_IMAGE_PIXELS = 40_000_000
GEMINI_MODEL = "gemini-3.8-flash"
OVERLOAD_RETRY_AFTER_SECONDS = 300
TEMPORARILY_BUSY_MESSAGE = (
    "AI image analysis is temporarily busy. Please try again in a few minutes."
)
CONFIGURATION_ERROR_MESSAGE = (
    "AI image analysis is unavailable due to a server configuration issue."
)
INVALID_MODEL_MESSAGE = (
    "AI image analysis is temporarily unavailable. Please try again later."
)
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)

ANALYSIS_PROMPT = """Analyze only visible evidence in this waste image.
Return a JSON object matching the supplied schema.
Classify the dominant visible waste as Plastic, Paper, Metal, Organic,
General/Mixed, or Unknown. Assess visible accumulation as Minimal, Moderate,
Heavy, or Not assessable. Assess overflow as Visible, Possible, or Not Visible.
Set severity to LOW, MEDIUM, or HIGH only when supported by visible accumulation;
otherwise set it to null and mark the analysis uncertain. If the image is unclear,
does not show waste, or does not provide enough evidence, use category Unknown,
accumulation Not assessable, null overflow and severity, and explain the limitation.
Do not infer hidden conditions, location, cause, or contents. Recommendations must
be proportionate to visible evidence. Set is_uncertain and provide uncertainty_reason
whenever any requested assessment is unclear; otherwise set is_uncertain false and
uncertainty_reason null."""


def validate_image(content: bytes, mime_type: str) -> None:
    """Reject unsupported, mismatched, corrupt, or excessively large images."""
    expected_format = ALLOWED_IMAGE_TYPES.get(mime_type.lower())
    if expected_format is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a JPEG, PNG, or WebP image.",
        )
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image exceeds the 8 MB upload limit.",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded image is empty or invalid.",
        )

    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != expected_format:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="Image content does not match its declared media type.",
                )
            width, height = image.size
            if (
                width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Image dimensions exceed the supported limit.",
                )
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded image is empty or invalid.",
        ) from exc


def _remove_additional_properties(schema: object) -> None:
    if isinstance(schema, dict):
        schema.pop("additionalProperties", None)
        for value in schema.values():
            _remove_additional_properties(value)
    elif isinstance(schema, list):
        for value in schema:
            _remove_additional_properties(value)


def _sanitize_provider_message(message: object, api_key: Optional[str]) -> str:
    safe_message = str(message or "")
    if api_key:
        safe_message = safe_message.replace(api_key, "[REDACTED]")
    safe_message = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", safe_message)
    safe_message = re.sub(
        r"(?i)(api[_-]?key|authorization|x-goog-api-key)(\s*[:=]\s*|\s+)"
        r"(?:bearer\s+)?[^\s,;\"']+",
        r"\1=[REDACTED]",
        safe_message,
    )
    safe_message = re.sub(
        r"(?i)data:[^;,\s]+;base64,[A-Za-z0-9+/=]+",
        "[IMAGE_DATA_REDACTED]",
        safe_message,
    )
    safe_message = re.sub(r"\b[A-Za-z0-9+/]{256,}={0,2}\b", "[DATA_REDACTED]", safe_message)
    return " ".join(safe_message.split())[:1000]


def _is_temporary_overload(provider_status: Optional[int], message: str) -> bool:
    if provider_status in (429, 503):
        return True
    normalized_message = message.lower()
    return any(
        phrase in normalized_message
        for phrase in ("high demand", "overloaded", "temporarily unavailable", "temporarily busy")
    )


def _is_invalid_api_key(provider_status: Optional[int], message: str) -> bool:
    if provider_status in (401, 403):
        return True
    normalized_message = message.lower().replace("_", " ")
    return any(
        phrase in normalized_message
        for phrase in (
            "api key not valid",
            "invalid api key",
            "api key is invalid",
            "api key invalid",
        )
    )


def _is_invalid_model(provider_status: Optional[int], message: str) -> bool:
    if provider_status == 404:
        return True
    normalized_message = message.lower()
    return bool(
        re.search(r"\bmodel\b.{0,100}\b(not found|invalid|unknown)\b", normalized_message)
        or re.search(r"\b(invalid|unknown)\b.{0,50}\bmodel\b", normalized_message)
        or "not supported for generatecontent" in normalized_message
    )


class GeminiWasteAnalysisService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        client_factory: Optional[Callable[..., genai.Client]] = None,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client_factory = client_factory or genai.Client

    async def analyze_image(self, image_bytes: bytes, mime_type: str) -> WasteAnalysisResponse:
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Waste analysis is not configured on the server.",
            )
        started_at = time.perf_counter()
        try:
            return await asyncio.to_thread(self._request_analysis, image_bytes, mime_type)
        except httpx.TimeoutException as exc:
            _log_request_failure(
                "Gemini waste analysis request timed out",
                exc,
                started_at,
                timeout_source="http_transport",
            )
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Gemini analysis timed out. Please try again.",
            ) from exc
        except TimeoutError as exc:
            _log_request_failure(
                "Gemini waste analysis request timed out",
                exc,
                started_at,
                timeout_source="sdk_timeout",
            )
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Gemini analysis timed out. Please try again.",
            ) from exc
        except errors.APIError as exc:
            provider_code = getattr(exc, "code", None)
            provider_message = _sanitize_provider_message(exc.message, self.api_key)
            if _is_temporary_overload(provider_code, provider_message):
                logger.warning(
                    "Gemini provider is temporarily busy: %s",
                    provider_message or "Provider returned an overload response.",
                    extra={
                        "event": "gemini_provider_overloaded",
                        "exception_type": type(exc).__name__,
                        "provider_status": provider_code,
                        "elapsed_ms": _elapsed_ms(started_at),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=TEMPORARILY_BUSY_MESSAGE,
                    headers={"Retry-After": str(OVERLOAD_RETRY_AFTER_SECONDS)},
                ) from exc
            if provider_code in (408, 504):
                _log_request_failure(
                    "Gemini provider request timed out",
                    exc,
                    started_at,
                    provider_status=provider_code,
                    timeout_source=f"provider_http_{provider_code}",
                )
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Gemini analysis timed out. Please try again.",
                ) from exc
            if _is_invalid_api_key(provider_code, provider_message):
                logger.error(
                    "Gemini API authentication or authorization failed: %s",
                    provider_message or "Provider rejected the configured credentials.",
                    extra={
                        "event": "gemini_authentication_failed",
                        "exception_type": type(exc).__name__,
                        "provider_status": provider_code,
                        "elapsed_ms": _elapsed_ms(started_at),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=CONFIGURATION_ERROR_MESSAGE,
                ) from exc
            if _is_invalid_model(provider_code, provider_message):
                logger.error(
                    "Gemini model is unavailable or invalid: %s",
                    provider_message or "Provider did not recognize the configured model.",
                    extra={
                        "event": "gemini_model_invalid",
                        "exception_type": type(exc).__name__,
                        "provider_status": provider_code,
                        "elapsed_ms": _elapsed_ms(started_at),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=INVALID_MODEL_MESSAGE,
                ) from exc
            logger.error(
                "Gemini waste analysis provider request failed: %s",
                provider_message or "No provider message.",
                extra={
                    "event": "gemini_provider_request_failed",
                    "exception_type": type(exc).__name__,
                    "provider_status": provider_code,
                    "elapsed_ms": _elapsed_ms(started_at),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini could not analyze the image. Please try again later.",
            ) from exc
        except ValidationError as exc:
            logger.warning(
                "Gemini returned a response that did not match the analysis schema",
                extra={
                    "event": "gemini_response_validation_failed",
                    "exception_type": type(exc).__name__,
                    "provider_status": None,
                    "elapsed_ms": _elapsed_ms(started_at),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini returned an invalid analysis response.",
            ) from exc
        except _MalformedGeminiResponse as exc:
            logger.warning(
                "Gemini returned an empty or malformed analysis response",
                extra={
                    "event": "gemini_response_malformed",
                    "exception_type": type(exc).__name__,
                    "provider_status": None,
                    "elapsed_ms": _elapsed_ms(started_at),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini returned an invalid analysis response.",
            ) from exc
        except Exception as exc:
            logger.error(
                "Unexpected Gemini waste analysis failure",
                extra={
                    "event": "gemini_request_failed_unexpectedly",
                    "exception_type": type(exc).__name__,
                    "provider_status": None,
                    "elapsed_ms": _elapsed_ms(started_at),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini could not analyze the image. Please try again later.",
            ) from exc

    def _request_analysis(self, image_bytes: bytes, mime_type: str) -> WasteAnalysisResponse:
        client = self.client_factory(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                timeout=60_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        try:
            response_schema = WasteAnalysisResponse.model_json_schema()
            _remove_additional_properties(response_schema)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    ANALYSIS_PROMPT,
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                ),
            )
            if response.parsed is not None:
                return WasteAnalysisResponse.model_validate(response.parsed)
            if response.text:
                return WasteAnalysisResponse.model_validate_json(response.text)
            raise _MalformedGeminiResponse("Gemini returned no structured analysis.")
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()


def get_waste_analysis_service() -> GeminiWasteAnalysisService:
    return GeminiWasteAnalysisService()


class _MalformedGeminiResponse(Exception):
    pass


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)


def _log_request_failure(
    message: str,
    exc: Exception,
    started_at: float,
    *,
    timeout_source: str,
    provider_status: Optional[int] = None,
) -> None:
    logger.warning(
        message,
        extra={
            "event": "gemini_request_timeout",
            "timeout_source": timeout_source,
            "exception_type": type(exc).__name__,
            "provider_status": provider_status,
            "elapsed_ms": _elapsed_ms(started_at),
        },
    )
