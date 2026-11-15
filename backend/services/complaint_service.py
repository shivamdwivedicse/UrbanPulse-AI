"""Citizen complaint workflows and optional image validation/storage."""

from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, status
from PIL import Image, UnidentifiedImageError

from backend.database.complaint_repository import ComplaintRepository, PROJECT_ROOT
from backend.schemas.complaint import (
    ComplaintCategory,
    ComplaintCreate,
    ComplaintPriority,
    ComplaintStatus,
)


MAX_COMPLAINT_IMAGE_BYTES = 5 * 1024 * 1024
COMPLAINT_UPLOAD_DIRECTORY = PROJECT_ROOT / "backend" / "uploads" / "complaints"
_IMAGE_FORMATS = {
    "image/jpeg": ("JPEG", ".jpg"),
    "image/png": ("PNG", ".png"),
    "image/webp": ("WEBP", ".webp"),
}
_COMPLAINT_ID_PATTERN = re.compile(r"^CMP-[A-F0-9]{32}$")


def validate_complaint_image(content: bytes, content_type: str) -> str:
    image_type = _IMAGE_FORMATS.get(content_type.lower())
    if image_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a JPEG, PNG, or WebP complaint image.",
        )
    if len(content) > MAX_COMPLAINT_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Complaint image exceeds the 5 MB upload limit.",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded complaint image is empty or invalid.",
        )
    expected_format, extension = image_type
    try:
        from io import BytesIO

        with Image.open(BytesIO(content)) as image:
            if image.format != expected_format:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="Image content does not match its declared media type.",
                )
            if image.width * image.height > 40_000_000:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Complaint image dimensions exceed the supported limit.",
                )
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded complaint image is empty or invalid.",
        ) from exc
    return extension


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ComplaintService:
    def __init__(
        self,
        repository: Optional[ComplaintRepository] = None,
        upload_directory: Path = COMPLAINT_UPLOAD_DIRECTORY,
    ):
        self.repository = repository or ComplaintRepository()
        self.upload_directory = Path(upload_directory)

    def create(
        self, complaint: ComplaintCreate, image_content: Optional[bytes] = None, image_type: Optional[str] = None
    ) -> dict[str, object]:
        image_path: Optional[str] = None
        saved_path: Optional[Path] = None
        if image_content is not None:
            if image_type is None:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="The complaint image media type is required.",
                )
            extension = validate_complaint_image(image_content, image_type)
            filename = f"{uuid4().hex}{extension}"
            saved_path = self.upload_directory / filename
            try:
                self.upload_directory.mkdir(parents=True, exist_ok=True)
                saved_path.write_bytes(image_content)
            except OSError as exc:
                if saved_path.exists():
                    saved_path.unlink()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Unable to store the complaint image.",
                ) from exc
            image_path = filename

        now = _utc_now()
        complaint_id = f"CMP-{uuid4().hex.upper()}"
        values = complaint.model_dump()
        values.update(
            complaint_id=complaint_id,
            category=complaint.category.value,
            priority=complaint.priority.value,
            latitude=complaint.latitude,
            longitude=complaint.longitude,
            image_path=image_path,
            status=ComplaintStatus.SUBMITTED.value,
            created_at=now,
            updated_at=now,
        )
        try:
            return self.repository.create(values)
        except sqlite3.IntegrityError as exc:
            if saved_path is not None:
                saved_path.unlink(missing_ok=True)
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A complaint with this identifier already exists.",
                ) from exc
            raise
        except Exception:
            if saved_path is not None:
                saved_path.unlink(missing_ok=True)
            raise

    def list(
        self,
        complaint_status: Optional[ComplaintStatus] = None,
        category: Optional[ComplaintCategory] = None,
        priority: Optional[ComplaintPriority] = None,
    ) -> list[dict[str, object]]:
        return self.repository.list(
            complaint_status=complaint_status,
            category=category,
            priority=priority,
        )

    def get(self, complaint_id: str) -> dict[str, object]:
        if not _COMPLAINT_ID_PATTERN.fullmatch(complaint_id):
            raise HTTPException(status_code=404, detail="Complaint not found.")
        complaint = self.repository.get(complaint_id)
        if complaint is None:
            raise HTTPException(status_code=404, detail="Complaint not found.")
        return complaint

    def update_status(
        self, complaint_id: str, complaint_status: ComplaintStatus
    ) -> dict[str, object]:
        if not _COMPLAINT_ID_PATTERN.fullmatch(complaint_id):
            raise HTTPException(status_code=404, detail="Complaint not found.")
        complaint = self.repository.update_status(
            complaint_id, complaint_status, _utc_now()
        )
        if complaint is None:
            raise HTTPException(status_code=404, detail="Complaint not found.")
        return complaint

    def get_image_path(self, complaint_id: str) -> Path:
        complaint = self.get(complaint_id)
        stored_path = complaint.get("image_path")
        if not stored_path:
            raise HTTPException(status_code=404, detail="Complaint has no attached image.")
        resolved = (self.upload_directory / str(stored_path)).resolve()
        upload_root = self.upload_directory.resolve()
        if resolved.parent != upload_root or not resolved.is_file():
            raise HTTPException(status_code=404, detail="Complaint image not found.")
        return resolved
