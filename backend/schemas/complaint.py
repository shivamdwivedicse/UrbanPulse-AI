"""Validated API schemas for citizen complaints."""

from enum import Enum
from math import isfinite
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ComplaintStatus(str, Enum):
    SUBMITTED = "Submitted"
    UNDER_REVIEW = "Under Review"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"
    REJECTED = "Rejected"


class ComplaintCategory(str, Enum):
    GARBAGE_OVERFLOW = "Garbage Overflow"
    UNCOLLECTED_WASTE = "Uncollected Waste"
    ILLEGAL_DUMPING = "Illegal Dumping"
    DAMAGED_DUSTBIN = "Damaged Dustbin"
    OTHER = "Other"


class ComplaintPriority(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


def _clean_text(value: str, *, multiline: bool = False) -> str:
    value = value.strip()
    value = re.sub(r"[ \t]+", " ", value)
    if not multiline:
        value = re.sub(r"\s+", " ", value)
    if any(ord(character) < 32 and character not in ("\n", "\r", "\t") for character in value):
        raise ValueError("Text contains unsupported control characters.")
    return value


class ComplaintCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citizen_name: str = Field(min_length=2, max_length=100)
    contact: str = Field(min_length=3, max_length=120)
    category: ComplaintCategory
    description: str = Field(min_length=10, max_length=2000)
    location: str = Field(min_length=2, max_length=200)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    priority: ComplaintPriority = ComplaintPriority.MEDIUM

    @field_validator("citizen_name", "contact", "location", mode="before")
    @classmethod
    def sanitize_single_line_fields(cls, value: Any) -> Any:
        return _clean_text(value) if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def sanitize_description(cls, value: Any) -> Any:
        return _clean_text(value, multiline=True) if isinstance(value, str) else value

    @field_validator("latitude", "longitude")
    @classmethod
    def coordinates_must_be_finite(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not isfinite(value):
            raise ValueError("Coordinates must be finite numbers.")
        return value

    @model_validator(mode="after")
    def require_coordinate_pair(self) -> "ComplaintCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together.")
        return self


class ComplaintStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ComplaintStatus


class ComplaintRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complaint_id: str
    citizen_name: str
    contact: str
    category: ComplaintCategory
    description: str
    location: str
    latitude: Optional[float]
    longitude: Optional[float]
    image_path: Optional[str]
    status: ComplaintStatus
    priority: ComplaintPriority
    created_at: str
    updated_at: str


class ComplaintListResponse(BaseModel):
    total: int
    complaints: list[ComplaintRecord]
