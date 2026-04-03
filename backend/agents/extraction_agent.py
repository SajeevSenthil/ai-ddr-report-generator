from __future__ import annotations

import re
from typing import Iterable

from backend.models import Observation, ObservationCategory, ParsedBundle, ParsedDocument, SourceType
from backend.services.llm_service import LLMService


class ExtractionAgent:
    """Step 1: extract structured observations from parsed source documents."""

    ISSUE_KEYWORDS = {
        "damp": ObservationCategory.DAMPNESS,
        "moisture": ObservationCategory.DAMPNESS,
        "leak": ObservationCategory.LEAKAGE,
        "crack": ObservationCategory.CRACK,
        "hollow": ObservationCategory.STRUCTURAL,
        "spalling": ObservationCategory.STRUCTURAL,
        "thermal": ObservationCategory.THERMAL_ANOMALY,
        "temperature": ObservationCategory.THERMAL_ANOMALY,
    }
    AREA_PATTERN = re.compile(
        r"\b(hall|bedroom|kitchen|bathroom|wc|toilet|balcony|parking|living room|master bedroom|common bathroom)\b",
        re.IGNORECASE,
    )
    ALLOWED_PREFIXES = (
        "observed",
        "negative side description",
        "positive side description",
        "thermal",
        "temperature",
        "moisture",
    )
    NOISE_PATTERNS = (
        "inspection form",
        "complete",
        "score",
        "flagged items",
        "actions",
        "site details",
        "summary table",
        "previous structural audit",
        "previous repair work",
        "inspection date",
        "customer name",
        "mobile",
        "email",
        "address",
        "property type",
        "property age",
        "floors",
        "checklist",
        "checklists",
        "photo ",
        "impacted area",
        "negative side photographs",
        "positive side photographs",
        "stuctural condition of rcc members 100%",
    )
    QUESTION_PREFIXES = (
        "condition of ",
        "are there any",
        "are the ",
        "leakage during",
        "leakage due to",
        "internal wc/bath/balcony leakage observed",
    )

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    def run(self, bundle: ParsedBundle) -> list[Observation]:
        if self.llm_service.is_configured():
            try:
                return self._run_with_llm(bundle)
            except Exception:
                pass
        return self._run_with_heuristics(bundle)

    def _run_with_llm(self, bundle: ParsedBundle) -> list[Observation]:
        payload = {
            "inspection_text": bundle.inspection.full_text[:24000],
            "thermal_text": bundle.thermal.full_text[:24000],
            "inspection_images": [image.model_dump() for image in bundle.inspection.images],
            "thermal_images": [image.model_dump() for image in bundle.thermal.images],
        }
        response = self.llm_service.generate_json(
            task_name="extraction_agent",
            instructions=(
                "Extract only explicitly supported observations from both documents. "
                "Do not infer root cause, severity, or actions. Return JSON with key "
                "'observations' as an array matching the observation schema."
            ),
            payload=payload,
        )
        observations = response.get("observations", [])
        return [Observation.model_validate(item) for item in observations]

    def _run_with_heuristics(self, bundle: ParsedBundle) -> list[Observation]:
        extracted: list[Observation] = []
        extracted.extend(self._extract_from_document(bundle.inspection))
        thermal_observations = self._extract_from_document(bundle.thermal)
        extracted.extend(
            observation
            for observation in thermal_observations
            if observation.area != "Not Available"
        )
        return extracted

    def _extract_from_document(self, document: ParsedDocument) -> list[Observation]:
        observations: list[Observation] = []
        for page_number, page_text in enumerate(document.pages, start=1):
            lines = [line.strip() for line in page_text.splitlines() if line.strip()]
            for line in lines:
                cleaned_line = self._clean_line(line)
                if not cleaned_line or self._should_skip_line(cleaned_line, document.document_type):
                    continue
                category = self._infer_category(cleaned_line)
                if category == ObservationCategory.OTHER and document.document_type == SourceType.INSPECTION:
                    continue
                area = self._infer_area(cleaned_line, lines)
                mapped_images = [
                    image.path
                    for image in document.images
                    if image.page_number == page_number and (image.mapped_area == area or area == "Not Available")
                ][:2]
                observations.append(
                    Observation(
                        area=area,
                        issue=cleaned_line,
                        category=category,
                        source=document.document_type,
                        images=mapped_images,
                        confidence=0.6 if category != ObservationCategory.OTHER else 0.35,
                        thermal_support=document.document_type == SourceType.THERMAL,
                        evidence=[cleaned_line],
                        page_references=[page_number],
                        raw_text=cleaned_line,
                    )
                )
        return self._dedupe_exact(observations)

    def _clean_line(self, text: str) -> str:
        text = text.replace("\x00", "")
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^\d+(\.\d+)*\s*", "", text)
        return text

    def _should_skip_line(self, text: str, document_type: SourceType) -> bool:
        lowered = text.lower()
        if len(lowered) < 12:
            return True
        if any(pattern in lowered for pattern in self.NOISE_PATTERNS):
            return True
        if any(lowered.startswith(prefix) for prefix in self.QUESTION_PREFIXES):
            return True
        if lowered.endswith(" n/a") or " n/a " in lowered:
            return True
        if lowered.endswith(" yes") or lowered.endswith(" no"):
            return True

        has_issue_keyword = any(keyword in lowered for keyword in self.ISSUE_KEYWORDS)
        has_allowed_prefix = lowered.startswith(self.ALLOWED_PREFIXES)

        if document_type == SourceType.INSPECTION:
            return not (has_issue_keyword and has_allowed_prefix)
        return not has_issue_keyword

    def _infer_category(self, text: str) -> ObservationCategory:
        lowered = text.lower()
        for keyword, category in self.ISSUE_KEYWORDS.items():
            if keyword in lowered:
                return category
        return ObservationCategory.OTHER

    def _infer_area(self, line: str, lines: Iterable[str]) -> str:
        match = self.AREA_PATTERN.search(line)
        if match:
            return match.group(0).title()
        for candidate in lines:
            candidate_match = self.AREA_PATTERN.search(candidate)
            if candidate_match:
                return candidate_match.group(0).title()
        return "Not Available"

    def _dedupe_exact(self, observations: list[Observation]) -> list[Observation]:
        seen: set[tuple[str, str, str]] = set()
        result: list[Observation] = []
        for observation in observations:
            key = (
                observation.area.lower(),
                observation.issue.lower(),
                observation.source.value,
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(observation)
        return result
