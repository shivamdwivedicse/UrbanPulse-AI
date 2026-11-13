"""
Pydantic schemas for API health and diagnostics.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ModelStatusSchema(BaseModel):
    loaded: bool = Field(..., description="Whether the ML model is currently loaded in memory")
    model_name: str = Field(..., description="Name of the champion model estimator")
    target_name: str = Field(..., description="Target variable predicted by the model")
    features: List[str] = Field(..., description="Ordered list of required feature names")


class HealthResponseSchema(BaseModel):
    status: str = Field(..., example="healthy")
    app_name: str = Field(..., example="UrbanPulse AI - Smart City Waste Management API")
    version: str = Field(..., example="1.0.0")
    model_status: ModelStatusSchema
