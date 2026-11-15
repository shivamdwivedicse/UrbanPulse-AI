"""Waste image analysis endpoint."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from backend.schemas.waste_analysis import WasteAnalysisResponse
from backend.services.gemini_waste_service import (
    MAX_IMAGE_BYTES,
    GeminiWasteAnalysisService,
    get_waste_analysis_service,
    validate_image,
)


router = APIRouter(prefix="/api/v1/waste", tags=["Waste Image Analysis"])


@router.post(
    "/analyze",
    response_model=WasteAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze Waste Image",
    description="Classify visible waste and assess accumulation and overflow using Gemini Vision.",
    responses={
        413: {"description": "Image or image dimensions exceed the supported limit"},
        415: {"description": "Unsupported image media type"},
        422: {"description": "Invalid image"},
        502: {"description": "Gemini provider or model failure, or malformed response"},
        503: {"description": "Gemini is temporarily busy or server credentials are invalid"},
        504: {"description": "Gemini request timed out"},
    },
)
async def analyze_waste_image(
    image: UploadFile = File(...),
    service: GeminiWasteAnalysisService = Depends(get_waste_analysis_service),
) -> WasteAnalysisResponse:
    if image.content_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a JPEG, PNG, or WebP image.",
        )

    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image exceeds the 8 MB upload limit.",
        )
    validate_image(image_bytes, image.content_type)
    return await service.analyze_image(image_bytes, image.content_type.lower())
