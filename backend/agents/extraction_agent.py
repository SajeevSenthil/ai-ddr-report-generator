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
        r"\b(hall|bedroom|common bedroom|kitchen|bathroom|common bathroom|master bedroom|mb bathroom|wc|toilet|balcony|parking|parking area|living room|external wall|exterior wall|rcc|rcc members|terrace|plaster|paint adhesion|plaster substrate)\b",
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
    STRUCTURAL_PATTERNS = (
        (
            r"Condition of cracks observed on RCC Column and Beam\s+(Moderate|Poor|Good)",
            "RCC Members",
            "Cracks observed in RCC columns and beams",
            ObservationCategory.CRACK,
        ),
        (
            r"Are there any major or minor cracks observed over external surface\?\s+(Moderate|Poor|Good)",
            "Exterior Walls",
            "Cracks observed on exterior wall surfaces",
            ObservationCategory.CRACK,
        ),
        (
            r"Algae fungus and Moss observed on external wall\?\s+(Moderate|Poor|Good)",
            "Exterior Walls",
            "Algae, fungus, or moss observed on external wall surfaces",
            ObservationCategory.DAMPNESS,
        ),
        (
            r"Condition of corrosion/spalling of concrete/exposed reinforcement observed in column/beams/roof slab ceiling\s+(Moderate|Poor|Good)",
            "RCC Members",
            "Corrosion or spalling observed in RCC members",
            ObservationCategory.STRUCTURAL,
        ),
        (
            r"Loose plaster/hollow sond on external surfaces\?if observed,\s+(Moderate|Poor|Good)",
            "Exterior Walls",
            "Loose plaster or hollow sound noted on external surfaces",
            ObservationCategory.STRUCTURAL,
        ),
        (
            r"Chalking and flaking in paint film\.\s+(Moderate|Poor|Good)",
            "Paint Adhesion",
            "Chalking or flaking observed in paint film",
            ObservationCategory.STRUCTURAL,
        ),
    )

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    def run(self, bundle: ParsedBundle) -> list[Observation]:
        deterministic = self._extract_deterministic_inspection_observations(bundle.inspection)
        if self.llm_service.is_configured():
            try:
                llm_observations = self._run_with_llm(bundle)
                return self._dedupe_exact(llm_observations + deterministic)
            except Exception:
                pass
        return self._dedupe_exact(self._run_with_heuristics(bundle) + deterministic)

    def _run_with_llm(self, bundle: ParsedBundle) -> list[Observation]:
        payload = {
            "inspection_pages": [
                {"page_number": index + 1, "text": text[:4000]}
                for index, text in enumerate(bundle.inspection.pages[:20])
            ],
            "thermal_pages": [
                {"page_number": index + 1, "text": text[:2500]}
                for index, text in enumerate(bundle.thermal.pages[:20])
            ],
            "inspection_images": [image.model_dump() for image in bundle.inspection.images],
            "thermal_images": [image.model_dump() for image in bundle.thermal.images],
        }
        response = self.llm_service.generate_json(
            task_name="extraction_agent",
            instructions=(
                "Extract only explicitly supported observations from the inspection and thermal documents.\n"
                "Focus on real findings such as dampness, leakage, cracks, tile hollowness, spalling, corrosion, or thermal anomalies.\n"
                "Ignore form boilerplate, metadata, checklist questions, repeated yes/no prompts, photo labels, and generic temperature headers unless they support a named anomaly.\n"
                "Prefer inspection summary-table style findings when available.\n"
                "Use thermal observations only when they can support a real issue or clearly indicate an anomaly.\n"
                "For each observation include:\n"
                "- area\n"
                "- issue\n"
                "- category\n"
                "- source\n"
                "- images (relevant only)\n"
                "- confidence\n"
                "- thermal_support\n"
                "- evidence\n"
                "- page_references\n"
                "- raw_text\n"
                "Do not infer root cause, severity, or actions yet.\n"
                "Return JSON with key 'observations' only."
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

    def _extract_deterministic_inspection_observations(self, document: ParsedDocument) -> list[Observation]:
        observations: list[Observation] = []
        observations.extend(self._extract_impacted_area_pairs(document))
        observations.extend(self._extract_summary_table_pairs(document))
        observations.extend(self._extract_structural_checklist_findings(document))
        return observations

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

    def _extract_impacted_area_pairs(self, document: ParsedDocument) -> list[Observation]:
        normalized = " ".join(document.full_text.replace("\x00", " ").split())
        pattern = re.compile(
            r"Impacted Area\s+\d+\s+Negative side Description\s+(?P<negative>.+?)\s+Negative side photographs.*?"
            r"Positive side Description\s+(?P<positive>.+?)\s+Positive side photographs",
            re.IGNORECASE,
        )
        observations: list[Observation] = []
        for match in pattern.finditer(normalized):
            negative = self._clean_line(match.group("negative"))
            positive = self._clean_line(match.group("positive"))
            if not negative:
                continue
            area = self._infer_area(negative, [negative, positive])
            category = self._infer_category(f"{negative} {positive}")
            observations.append(
                self._make_observation(
                    document=document,
                    area=area,
                    issue=negative,
                    category=category,
                    evidence=[negative, f"Positive side: {positive}"],
                    raw_text=f"{negative}\nPositive side: {positive}",
                )
            )
        return observations

    def _extract_summary_table_pairs(self, document: ParsedDocument) -> list[Observation]:
        text = document.full_text
        match = re.search(r"SUMMARY TABLE(.+?)(Appendix|Photo 1|$)", text, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        normalized = " ".join(match.group(1).replace("\x00", " ").split())
        row_pattern = re.compile(
            r"\d+\s+(?P<negative>Observed.+?)\s+\d+\.\d+\s+(?P<positive>Observed.+?)(?=\s+\d+\s+Observed|\Z)",
            re.IGNORECASE,
        )
        observations: list[Observation] = []
        for row in row_pattern.finditer(normalized):
            negative = self._clean_line(row.group("negative"))
            positive = self._clean_line(row.group("positive"))
            if not negative:
                continue
            area = self._infer_area(negative, [negative, positive])
            category = self._infer_category(f"{negative} {positive}")
            observations.append(
                self._make_observation(
                    document=document,
                    area=area,
                    issue=negative,
                    category=category,
                    evidence=[negative, f"Positive side: {positive}"],
                    raw_text=f"{negative}\nPositive side: {positive}",
                )
            )
        return observations

    def _extract_structural_checklist_findings(self, document: ParsedDocument) -> list[Observation]:
        normalized = " ".join(document.full_text.replace("\x00", " ").split())
        observations: list[Observation] = []
        for pattern, area, issue, category in self.STRUCTURAL_PATTERNS:
            for match in re.finditer(pattern, normalized, re.IGNORECASE):
                rating = match.group(1).title()
                observations.append(
                    self._make_observation(
                        document=document,
                        area=area,
                        issue=f"{issue} ({rating})",
                        category=category,
                        evidence=[issue, f"Checklist severity: {rating}"],
                        raw_text=f"{issue} {rating}",
                    )
                )
        return observations

    def _make_observation(
        self,
        document: ParsedDocument,
        area: str,
        issue: str,
        category: ObservationCategory,
        evidence: list[str],
        raw_text: str,
    ) -> Observation:
        matched_pages = self._find_matching_pages(document, area, issue, evidence)
        mapped_images = [
            image.path
            for image in document.images
            if image.page_number in matched_pages
        ][:2]
        if not mapped_images and area != "Not Available":
            mapped_images = [
                image.path
                for image in document.images
                if image.mapped_area.lower() == area.lower()
            ][:2]
        return Observation(
            area=area,
            issue=issue,
            category=category,
            source=document.document_type,
            images=mapped_images,
            confidence=0.85,
            thermal_support=document.document_type == SourceType.THERMAL,
            evidence=evidence,
            page_references=matched_pages,
            raw_text=raw_text,
        )

    def _find_matching_pages(
        self,
        document: ParsedDocument,
        area: str,
        issue: str,
        evidence: list[str],
    ) -> list[int]:
        terms = [area, issue] + evidence
        pages: list[int] = []
        for idx, page_text in enumerate(document.pages, start=1):
            lowered = page_text.lower()
            if any(term and term.lower() in lowered for term in terms if term != "Not Available"):
                pages.append(idx)
            if len(pages) >= 2:
                break
        return pages or [1]
