from __future__ import annotations

from collections import defaultdict

from backend.models import Observation, ObservationCategory, SourceType
from backend.services.llm_service import LLMService


class DeduplicationAgent:
    """Step 2: merge duplicate or semantically overlapping observations."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    def run(self, observations: list[Observation]) -> list[Observation]:
        if self.llm_service.is_configured():
            try:
                return self._run_with_llm(observations)
            except Exception:
                pass
        return self._run_with_rules(observations)

    def _run_with_llm(self, observations: list[Observation]) -> list[Observation]:
        response = self.llm_service.generate_json(
            task_name="deduplication_agent",
            instructions=(
                "Merge only true duplicates or clearly overlapping observations. "
                "Preserve evidence, page references, image paths, and source provenance. "
                "Return JSON with key 'observations'."
            ),
            payload={"observations": [item.model_dump() for item in observations]},
        )
        return [Observation.model_validate(item) for item in response.get("observations", [])]

    def _run_with_rules(self, observations: list[Observation]) -> list[Observation]:
        grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
        for observation in observations:
            issue_key = self._normalize_issue(observation.issue)
            grouped[(observation.area.lower(), issue_key)].append(observation)

        merged: list[Observation] = []
        for group in grouped.values():
            base = group[0]
            images = sorted({image for item in group for image in item.images})
            evidence = list(dict.fromkeys(text for item in group for text in item.evidence))
            pages = sorted({page for item in group for page in item.page_references})
            has_thermal = any(item.source == SourceType.THERMAL for item in group)
            source = SourceType.THERMAL if all(item.source == SourceType.THERMAL for item in group) else SourceType.INSPECTION
            merged.append(
                Observation(
                    area=base.area,
                    issue=base.issue,
                    category=self._pick_category(group),
                    source=source,
                    images=images,
                    confidence=max(item.confidence for item in group),
                    thermal_support=has_thermal or base.thermal_support,
                    temperature_range=base.temperature_range,
                    evidence=evidence,
                    page_references=pages,
                    raw_text="\n".join(item.raw_text for item in group if item.raw_text),
                )
            )
        return merged

    def _normalize_issue(self, issue: str) -> str:
        lowered = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in issue.lower())
        replacements = {
            "negative side description": "",
            "positive side description": "",
            "observed": "",
            "condition of": "",
            "at the": "",
            "level": "",
            "side": "",
            "description": "",
            "issue": "",
            "observed ": "",
        }
        for source, target in replacements.items():
            lowered = lowered.replace(source, target)

        tokens = [
            token
            for token in lowered.split()
            if token
            and token
            not in {
                "the",
                "and",
                "of",
                "at",
                "between",
                "on",
                "to",
                "under",
                "all",
                "time",
                "yes",
                "moderate",
                "mild",
            }
        ]
        if "dampness" in tokens:
            return "dampness"
        if "leakage" in tokens or "leak" in tokens:
            return "leakage"
        if "hollowness" in tokens or "hollow" in tokens:
            return "tile hollowness"
        if "crack" in tokens or "cracks" in tokens:
            return "cracks"
        if "spalling" in tokens or "corrosion" in tokens:
            return "structural distress"
        return " ".join(tokens[:8])

    def _pick_category(self, items: list[Observation]) -> ObservationCategory:
        ranked = [
            ObservationCategory.STRUCTURAL,
            ObservationCategory.LEAKAGE,
            ObservationCategory.DAMPNESS,
            ObservationCategory.CRACK,
            ObservationCategory.THERMAL_ANOMALY,
            ObservationCategory.OTHER,
        ]
        available = {item.category for item in items}
        for category in ranked:
            if category in available:
                return category
        return ObservationCategory.OTHER
