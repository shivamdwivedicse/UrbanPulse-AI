"""
Smart Bin fleet and prediction endpoints.
"""

from fastapi import APIRouter, Depends, Path, status
from backend.schemas.bin import BinInfoSchema, BinListResponseSchema
from backend.schemas.prediction import ErrorResponseSchema, FillLevelPredictionResponseSchema
from backend.services.bin_service import BinService, get_bin_service

router = APIRouter(prefix="/api/v1/bins", tags=["Smart Bins & Fill Predictions"])


@router.get(
    "",
    response_model=BinListResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="List Prototype Bins",
    description="Retrieve available prototype bins. Represents one historical research bin from verified telemetry.",
)
def list_bins(service: BinService = Depends(get_bin_service)) -> BinListResponseSchema:
    bins_data = service.get_available_bins()
    return BinListResponseSchema(
        total_bins=len(bins_data),
        bins=[BinInfoSchema(**b) for b in bins_data],
    )


@router.get(
    "/{bin_id}/prediction",
    response_model=FillLevelPredictionResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Predict Bin Fill-Level",
    description=(
        "Generate next-day fill-level prediction for a smart bin using historical "
        "sensor observations and the trained HistGradientBoosting Regressor."
    ),
    responses={
        404: {"model": ErrorResponseSchema, "description": "Bin not found"},
        422: {"model": ErrorResponseSchema, "description": "Insufficient observations"},
        500: {"model": ErrorResponseSchema, "description": "Inference engine error"},
    },
)
def predict_bin_fill(
    bin_id: str = Path(..., description="Prototype Bin Identifier (e.g., 'BIN-PROTOTYPE-01')"),
    service: BinService = Depends(get_bin_service),
) -> FillLevelPredictionResponseSchema:
    prediction_data = service.predict_fill_level(bin_id)
    return FillLevelPredictionResponseSchema(**prediction_data)
