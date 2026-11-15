"""Structured response schema for visible waste image analysis."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


WasteCategory = Literal["Plastic", "Paper", "Metal", "Organic", "General/Mixed", "Unknown"]
OverflowAssessment = Literal["Visible", "Possible", "Not Visible"]
Severity = Literal["LOW", "MEDIUM", "HIGH"]
AccumulationAssessment = Literal["Minimal", "Moderate", "Heavy", "Not assessable"]


class WasteAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: WasteCategory
    accumulation_assessment: AccumulationAssessment
    overflow_assessment: Optional[OverflowAssessment]
    severity: Optional[Severity]
    explanation: str = Field(min_length=1, max_length=1000)
    recommended_action: str = Field(min_length=1, max_length=500)
    is_uncertain: bool
    uncertainty_reason: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_uncertainty(self) -> "WasteAnalysisResponse":
        if self.is_uncertain and not self.uncertainty_reason:
            raise ValueError("uncertainty_reason is required when analysis is uncertain")
        if not self.is_uncertain and self.uncertainty_reason is not None:
            raise ValueError("uncertainty_reason must be omitted for certain analysis")
        if self.accumulation_assessment == "Not assessable" and not self.is_uncertain:
            raise ValueError("unassessable accumulation requires explicit uncertainty")
        if not self.is_uncertain and (self.overflow_assessment is None or self.severity is None):
            raise ValueError("certain analysis must include overflow and severity assessments")
        return self
