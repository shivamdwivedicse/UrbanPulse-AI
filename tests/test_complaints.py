from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.api.routes_complaints import get_complaint_service
from backend.database.complaint_repository import ComplaintRepository
from backend.main import app
from backend.services.complaint_service import ComplaintService


@pytest.fixture
def client(tmp_path: Path):
    database_path = tmp_path / "data" / "complaints.sqlite3"
    upload_directory = tmp_path / "uploads"

    def service_override() -> ComplaintService:
        return ComplaintService(
            repository=ComplaintRepository(database_path),
            upload_directory=upload_directory,
        )

    app.dependency_overrides[get_complaint_service] = service_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_complaint_service, None)


def valid_form(**overrides):
    values = {
        "citizen_name": "Asha Citizen",
        "contact": "asha@example.test",
        "category": "Garbage Overflow",
        "description": "Waste has been overflowing near the community park.",
        "location": "Community park entrance",
        "priority": "High",
    }
    values.update(overrides)
    return values


def make_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 4), color=(40, 201, 149)).save(output, format="PNG")
    return output.getvalue()


def test_database_initializes_and_records_persist(tmp_path):
    database_path = tmp_path / "complaints.sqlite3"
    first_repository = ComplaintRepository(database_path)
    assert database_path.is_file()
    assert first_repository.list() == []

    complaint = {
        "complaint_id": "CMP-0123456789AB",
        "citizen_name": "Asha Citizen",
        "contact": "asha@example.test",
        "category": "Garbage Overflow",
        "description": "Waste overflow reported near a park.",
        "location": "Community park",
        "latitude": None,
        "longitude": None,
        "image_path": None,
        "status": "Submitted",
        "priority": "Medium",
        "created_at": "2025-01-01T10:00:00+00:00",
        "updated_at": "2025-01-01T10:00:00+00:00",
    }
    first_repository.create(complaint)

    restarted_repository = ComplaintRepository(database_path)
    assert restarted_repository.get(complaint["complaint_id"])["citizen_name"] == "Asha Citizen"


def test_register_retrieve_filter_and_update_complaint(client):
    response = client.post("/api/v1/complaints", data=valid_form())
    assert response.status_code == 201
    created = response.json()
    assert created["complaint_id"].startswith("CMP-")
    assert created["status"] == "Submitted"
    assert created["priority"] == "High"
    assert created["image_path"] is None

    list_response = client.get("/api/v1/complaints")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["complaints"][0]["complaint_id"] == created["complaint_id"]

    filtered = client.get(
        "/api/v1/complaints",
        params={"status": "Submitted", "category": "Garbage Overflow", "priority": "High"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert client.get(f"/api/v1/complaints/{created['complaint_id']}").json()["location"] == (
        "Community park entrance"
    )

    updated = client.patch(
        f"/api/v1/complaints/{created['complaint_id']}/status",
        json={"status": "In Progress"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "In Progress"
    assert updated.json()["updated_at"] >= created["updated_at"]
    assert client.get("/api/v1/complaints?status=Resolved").json()["total"] == 0


def test_reject_invalid_fields_coordinates_and_filters(client):
    assert client.post(
        "/api/v1/complaints", data=valid_form(category="Unknown Category")
    ).status_code == 422
    assert client.post(
        "/api/v1/complaints", data=valid_form(latitude="91", longitude="10")
    ).status_code == 422
    assert client.post(
        "/api/v1/complaints", data=valid_form(latitude="10")
    ).status_code == 422
    assert client.get("/api/v1/complaints?status=Unknown").status_code == 422
    assert client.patch(
        "/api/v1/complaints/CMP-0123456789AB/status",
        json={"status": "Unknown"},
    ).status_code == 422
    assert client.post(
        "/api/v1/complaints", data=valid_form(citizen_name="  ")
    ).status_code == 422


def test_unknown_and_malformed_complaint_ids_return_404(client):
    assert client.get("/api/v1/complaints/not-an-id").status_code == 404
    assert client.get(
        "/api/v1/complaints/CMP-0123456789ABCDEF0123456789ABCDEF"
    ).status_code == 404
    assert client.patch(
        "/api/v1/complaints/CMP-0123456789ABCDEF0123456789ABCDEF/status",
        json={"status": "Resolved"},
    ).status_code == 404


def test_image_upload_checks_actual_content_and_stores_safe_relative_path(client, tmp_path):
    response = client.post(
        "/api/v1/complaints",
        data=valid_form(),
        files={"image": ("untrusted name.png", make_png(), "image/png")},
    )
    assert response.status_code == 201
    record = response.json()
    stored_path = record["image_path"]
    assert Path(stored_path).name == stored_path
    assert stored_path.endswith(".png")

    image_response = client.get(
        f"/api/v1/complaints/{record['complaint_id']}/image"
    )
    assert image_response.status_code == 200
    assert image_response.content == make_png()

    bad_content = client.post(
        "/api/v1/complaints",
        data=valid_form(),
        files={"image": ("photo.png", b"not an image", "image/png")},
    )
    assert bad_content.status_code == 422

    mismatched_content = client.post(
        "/api/v1/complaints",
        data=valid_form(),
        files={"image": ("photo.jpg", make_png(), "image/jpeg")},
    )
    assert mismatched_content.status_code == 415


def test_image_upload_enforces_five_megabyte_limit(client):
    response = client.post(
        "/api/v1/complaints",
        data=valid_form(),
        files={
            "image": (
                "oversized.png",
                b"x" * (5 * 1024 * 1024 + 1),
                "image/png",
            )
        },
    )
    assert response.status_code == 413
