"""
Pydantic schemas for Smart Bin representations.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class BinInfoSchema(BaseModel):
    bin_id: str = Field(..., example="BIN-PROTOTYPE-01", description="Unique prototype bin identifier")
    name: str = Field(..., example="Smart Waste Bin (Research Prototype)")
    waste_type: str = Field(..., example="General Waste", description="Category of waste stored")
    capacity_liters: int = Field(..., example=120, description="Bin volumetric capacity in liters")
    status: str = Field(..., example="active_historical_sample")
    data_source: str = Field(..., example="Research Dataset (Smart Bin Insights, 2018-2020)")
    total_historical_records: int = Field(..., example=659, description="Available cleaned historical observations")
    latest_reading_date: str = Field(..., example="2020-06-29 12:00:00")
    latest_recorded_fill_level: float = Field(..., example=0.0, description="Most recent historical fill level")
    fill_level_scale: str = Field(default="0 to 10 (0=Empty, 10=Full)")
    notes: str = Field(
        default="Prototype representing single-bin historical telemetry. Not connected to live physical IoT hardware."
    )


class BinListResponseSchema(BaseModel):
    total_bins: int = Field(..., example=1)
    bins: List[BinInfoSchema]
