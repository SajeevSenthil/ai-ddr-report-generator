from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    INSPECTION = "inspection"
    THERMAL = "thermal"


class ObservationCategory(str, Enum):
    DAMPNESS = "dampness"
    CRACK = "crack"
    LEAKAGE = "leakage"
    STRUCTURAL = "structural"
    THERMAL_ANOMALY = "thermal_anomaly"
    OTHER = "other"


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    NOT_AVAILABLE = "Not Available"


class ExtractedImage(BaseModel):
    id: str
    document_type: SourceType
    page_number: int
    path: str
    caption: str = "Image Not Available"
    mapped_area: str = "Not Available"


class TemperatureRange(BaseModel):
    minimum_celsius: float | None = None
    maximum_celsius: float | None = None


class Observation(BaseModel):
    area: str = "Not Available"
    issue: str = "Not Available"
    category: ObservationCategory = ObservationCategory.OTHER
    source: SourceType
    images: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    thermal_support: bool = False
    temperature_range: TemperatureRange | None = None
    evidence: list[str] = Field(default_factory=list)
    page_references: list[int] = Field(default_factory=list)
    raw_text: str | None = None


class EnrichedObservation(Observation):
    probable_root_cause: str = "Not Available"
    severity: SeverityLevel = SeverityLevel.NOT_AVAILABLE
    severity_reasoning: str = "Not Available"
    recommended_actions: list[str] = Field(default_factory=list)
    additional_notes: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class StructuredReport(BaseModel):
    property_issue_summary: str
    area_wise_observations: list[dict[str, Any]]
    probable_root_cause: str
    severity_assessment: str
    recommended_actions: list[str]
    additional_notes: list[str]
    missing_or_unclear_information: list[str]


class ParsedDocument(BaseModel):
    document_type: SourceType
    file_name: str
    full_text: str
    pages: list[str] = Field(default_factory=list)
    images: list[ExtractedImage] = Field(default_factory=list)


class ParsedBundle(BaseModel):
    inspection: ParsedDocument
    thermal: ParsedDocument


class PipelineResult(BaseModel):
    observations: list[Observation]
    deduplicated_observations: list[Observation]
    enriched_observations: list[EnrichedObservation]
    structured_report: StructuredReport
    markdown_report: str
