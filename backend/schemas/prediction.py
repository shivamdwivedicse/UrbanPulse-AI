"""
Pydantic schemas for Fill-Level Prediction responses.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class FeatureInputsSchema(BaseModel):
    lag_1: float = Field(..., description="Previous observation fill level")
    lag_2: float = Field(..., description="2 observations prior fill level")
    lag_3: float = Field(..., description="3 observations prior fill level")
    lag_7: float = Field(..., description="7 observations prior fill level")
    rolling_mean_3: float = Field(..., description="3-observation historical moving average")
    rolling_mean_7: float = Field(..., description="7-observation historical moving average")
    day_of_week: int = Field(..., description="Target forecast day of week (0=Mon, 6=Sun)")
    month: int = Field(..., description="Target forecast calendar month (1 to 12)")


class FillLevelPredictionResponseSchema(BaseModel):
    bin_id: str = Field(..., example="BIN-PROTOTYPE-01")
    prediction_timestamp: str = Field(..., description="Timestamp for which fill-level is forecast")
    forecast_horizon: str = Field(default="Next calendar observation (+1 day)")
    raw_prediction: float = Field(..., description="Unconstrained continuous output from regressor")
    bounded_prediction: float = Field(
        ..., ge=0.0, le=10.0, description="Physically valid fill level strictly bounded within [0.0, 10.0]"
    )
    was_clipped: bool = Field(..., description="Whether post-inference boundary clipping was triggered")
    clip_direction: str = Field(..., example="none", description="'lower' if raw < 0, 'upper' if raw > 10, or 'none'")
    model_name: str = Field(..., example="HistGradientBoosting Regressor")
    unit_range: str = Field(default="0–10", description="Continuous scale from 0.0 (empty) to 10.0 (completely full)")
    historical_base_date: str = Field(..., description="Most recent historical reading used to compute lags")
    features_used: FeatureInputsSchema


class ErrorResponseSchema(BaseModel):
    error: str = Field(..., example="Bin not found")
    detail: str = Field(..., example="Bin ID 'INVALID-999' is not recognized.")
