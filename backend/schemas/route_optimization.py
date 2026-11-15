"""Validated request and response models for illustrative route optimization."""

from enum import Enum
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CollectionPriority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class GeoPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("latitude", "longitude")
    @classmethod
    def coordinates_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Coordinates must be finite numbers.")
        return value


class DepotLocation(GeoPoint):
    name: str = Field(default="Depot", min_length=1, max_length=80)


class RouteStop(GeoPoint):
    bin_id: str = Field(min_length=1, max_length=80)
    fill_level: float = Field(ge=0, le=10)
    priority: CollectionPriority

    @field_validator("bin_id")
    @classmethod
    def bin_id_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Bin ID must not be blank.")
        return value

    @field_validator("fill_level")
    @classmethod
    def fill_level_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Fill level must be a finite number.")
        return value


class RouteOptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depot: DepotLocation
    stops: list[RouteStop] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_unique_bin_ids(self) -> "RouteOptimizeRequest":
        ids = [stop.bin_id.casefold() for stop in self.stops]
        if len(ids) != len(set(ids)):
            raise ValueError("Bin IDs must be unique.")
        return self


class OptimizedRouteStop(RouteStop):
    stop_number: int = Field(ge=1)
    distance_from_previous_km: float = Field(ge=0)


class RouteOptimizationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depot: DepotLocation
    stops: list[OptimizedRouteStop]
    total_estimated_distance_km: float = Field(ge=0)
    number_of_stops: int = Field(ge=1)
    optimization_status: str
    distance_methodology: str
    return_to_depot: bool
