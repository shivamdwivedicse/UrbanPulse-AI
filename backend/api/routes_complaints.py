"""Citizen complaint registration and administration APIs."""

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import ValidationError

from backend.schemas.complaint import (
    ComplaintCategory,
    ComplaintCreate,
    ComplaintListResponse,
    ComplaintPriority,
    ComplaintRecord,
    ComplaintStatus,
    ComplaintStatusUpdate,
)
from backend.services.complaint_service import (
    MAX_COMPLAINT_IMAGE_BYTES,
    ComplaintService,
)


router = APIRouter(prefix="/api/v1/complaints", tags=["Citizen Complaints"])


def get_complaint_service() -> ComplaintService:
    return ComplaintService()


@router.post(
    "",
    response_model=ComplaintRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Register a citizen complaint",
    responses={
        201: {"description": "Complaint registered"},
        409: {"description": "Duplicate complaint identifier"},
        413: {"description": "Image exceeds the upload limit"},
        415: {"description": "Unsupported image media type"},
        422: {"description": "Invalid complaint fields or image"},
    },
)
async def register_complaint(
    citizen_name: str = Form(...),
    contact: str = Form(...),
    category: ComplaintCategory = Form(...),
    description: str = Form(...),
    location: str = Form(...),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    priority: ComplaintPriority = Form(ComplaintPriority.MEDIUM),
    image: Optional[UploadFile] = File(None),
    service: ComplaintService = Depends(get_complaint_service),
) -> ComplaintRecord:
    try:
        payload = ComplaintCreate(
            citizen_name=citizen_name,
            contact=contact,
            category=category,
            description=description,
            location=location,
            latitude=latitude,
            longitude=longitude,
            priority=priority,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_input=False, include_context=False),
        ) from exc
    image_content = None
    image_type = None
    if image is not None:
        if image.content_type is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Upload a JPEG, PNG, or WebP complaint image.",
            )
        image_content = await image.read(MAX_COMPLAINT_IMAGE_BYTES + 1)
        image_type = image.content_type
    record = service.create(payload, image_content, image_type)
    return ComplaintRecord.model_validate(record)


@router.get(
    "",
    response_model=ComplaintListResponse,
    summary="List complaints with optional filters",
)
def list_complaints(
    complaint_status: Optional[ComplaintStatus] = Query(None, alias="status"),
    category: Optional[ComplaintCategory] = None,
    priority: Optional[ComplaintPriority] = None,
    service: ComplaintService = Depends(get_complaint_service),
) -> ComplaintListResponse:
    complaints = service.list(complaint_status, category, priority)
    return ComplaintListResponse(total=len(complaints), complaints=complaints)


@router.get(
    "/{complaint_id}",
    response_model=ComplaintRecord,
    summary="Retrieve complaint details",
    responses={404: {"description": "Complaint not found"}},
)
def get_complaint(
    complaint_id: str,
    service: ComplaintService = Depends(get_complaint_service),
) -> ComplaintRecord:
    return ComplaintRecord.model_validate(service.get(complaint_id))


@router.get(
    "/{complaint_id}/image",
    include_in_schema=False,
)
def get_complaint_image(
    complaint_id: str,
    service: ComplaintService = Depends(get_complaint_service),
) -> FileResponse:
    image_path = service.get_image_path(complaint_id)
    return FileResponse(image_path)


@router.patch(
    "/{complaint_id}/status",
    response_model=ComplaintRecord,
    summary="Update complaint status",
    responses={404: {"description": "Complaint not found"}},
)
def update_complaint_status(
    complaint_id: str,
    update: ComplaintStatusUpdate,
    service: ComplaintService = Depends(get_complaint_service),
) -> ComplaintRecord:
    return ComplaintRecord.model_validate(
        service.update_status(complaint_id, update.status)
    )
