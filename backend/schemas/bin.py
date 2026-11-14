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


class HistoryObservationSchema(BaseModel):
    datetime: str = Field(..., description="Historical observation timestamp")
    fill_level: float = Field(..., description="Recorded fill level on the 0–10 scale")


class BinHistoryResponseSchema(BaseModel):
    bin_id: str = Field(..., example="BIN-PROTOTYPE-01")
    data_source: str = Field(..., example="Research Dataset (Smart Bin Insights, 2018-2020)")
    is_live_iot: bool = Field(default=False, description="False for historical research data")
    fill_level_scale: str = Field(default="0 to 10 (0=Empty, 10=Full)")
    total_observations: int = Field(..., description="Number of cleaned historical readings")
    start_date: str = Field(..., description="Earliest observation timestamp")
    end_date: str = Field(..., description="Latest observation timestamp")
    min_fill_level: float = Field(..., description="Minimum recorded fill level")
    max_fill_level: float = Field(..., description="Maximum recorded fill level")
    average_fill_level: float = Field(..., description="Mean recorded fill level")
    observations: List[HistoryObservationSchema]
