"""
Health and system diagnostics route.
"""

from fastapi import APIRouter, Depends, status
from backend.schemas.health import HealthResponseSchema, ModelStatusSchema
from backend.services.bin_service import BinService, get_bin_service

router = APIRouter(tags=["Health & Diagnostics"])


@router.get(
    "/health",
    response_model=HealthResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="API Health & Diagnostics",
    description="Check system health and confirm the status of the ML prediction model.",
)
def get_health(service: BinService = Depends(get_bin_service)) -> HealthResponseSchema:
    model_status_data = service.get_model_status()
    return HealthResponseSchema(
        status="healthy",
        app_name="UrbanPulse AI - Smart City Waste Management API",
        version="1.0.0",
        model_status=ModelStatusSchema(**model_status_data),
    )
