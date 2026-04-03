from __future__ import annotations

from collections import defaultdict

from backend.models import EnrichedObservation, StructuredReport
from backend.services.llm_service import LLMService


class StructuringAgent:
    """Step 4: format enriched observations into the DDR template structure."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    def run(self, observations: list[EnrichedObservation]) -> StructuredReport:
        if self.llm_service.is_configured():
            try:
                return self._run_with_llm(observations)
            except Exception:
                pass
        return self._run_with_rules(observations)

    def _run_with_llm(self, observations: list[EnrichedObservation]) -> StructuredReport:
        response = self.llm_service.generate_json(
            task_name="structuring_agent",
            instructions=(
                "Convert enriched observations into the mandatory DDR sections. "
                "Use simple client-friendly language and preserve missing information explicitly. "
                "Return JSON matching the structured report format."
            ),
            payload={"observations": [item.model_dump() for item in observations]},
        )
        return StructuredReport.model_validate(response)

    def _run_with_rules(self, observations: list[EnrichedObservation]) -> StructuredReport:
        grouped: dict[str, list[EnrichedObservation]] = defaultdict(list)
        for observation in observations:
            grouped[observation.area].append(observation)

        area_entries = []
        root_causes: list[str] = []
        severity_lines: list[str] = []
        actions: list[str] = []
        notes: list[str] = []
        missing: list[str] = []

        for area, items in grouped.items():
            consolidated_items = self._consolidate_area_items(items)
            area_entries.append(
                {
                    "area": area,
                    "observations": [
                        {
                            "issue": item.issue,
                            "category": item.category.value,
                            "source": item.source.value,
                            "images": item.images or ["Image Not Available"],
                            "evidence": item.evidence,
                            "probable_root_cause": item.probable_root_cause,
                            "severity": item.severity.value,
                            "severity_reasoning": item.severity_reasoning,
                            "recommended_actions": item.recommended_actions,
                            "additional_notes": item.additional_notes,
                            "conflicts": item.conflicts,
                            "missing_information": item.missing_information,
                        }
                        for item in consolidated_items
                    ],
                }
            )
            root_causes.extend(
                item.probable_root_cause for item in consolidated_items if item.probable_root_cause != "Not Available"
            )
            severity_lines.extend(
                f"{item.area}: {item.severity.value} - {item.severity_reasoning}" for item in consolidated_items
            )
            actions.extend(action for item in consolidated_items for action in item.recommended_actions)
            notes.extend(note for item in consolidated_items for note in item.additional_notes if note != "Not Available")
            missing.extend(detail for item in consolidated_items for detail in item.missing_information)
            missing.extend(conflict for item in consolidated_items for conflict in item.conflicts)

        summary = self._build_summary(observations)
        return StructuredReport(
            property_issue_summary=summary,
            area_wise_observations=area_entries,
            probable_root_cause="\n".join(dict.fromkeys(root_causes)) or "Not Available",
            severity_assessment="\n".join(dict.fromkeys(severity_lines)) or "Not Available",
            recommended_actions=list(dict.fromkeys(actions)) or ["Not Available"],
            additional_notes=list(dict.fromkeys(notes)) or ["Not Available"],
            missing_or_unclear_information=list(dict.fromkeys(missing)) or ["Not Available"],
        )

    def _build_summary(self, observations: list[EnrichedObservation]) -> str:
        if not observations:
            return "No supported observations were extracted from the provided documents."
        areas = sorted({item.area for item in observations if item.area != "Not Available"})
        categories = sorted({item.category.value for item in observations})
        area_text = ", ".join(areas) if areas else "the available property areas"
        category_text = ", ".join(categories)
        return (
            f"The review identified {len(observations)} consolidated observation(s) across {area_text}. "
            f"The main reported issue types are {category_text}. Thermal findings were treated as supporting evidence only."
        )

    def _consolidate_area_items(self, items: list[EnrichedObservation]) -> list[EnrichedObservation]:
        grouped: dict[str, list[EnrichedObservation]] = defaultdict(list)
        for item in items:
            grouped[item.category.value].append(item)

        consolidated: list[EnrichedObservation] = []
        for category_items in grouped.values():
            base = category_items[0]
            phrases = [
                self._short_issue_phrase(item.issue)
                for item in category_items
                if self._short_issue_phrase(item.issue) not in {"Not Available", ""}
            ]
            evidence = list(dict.fromkeys(text for item in category_items for text in item.evidence))
            images = sorted({image for item in category_items for image in item.images}) or ["Image Not Available"]
            missing = list(dict.fromkeys(detail for item in category_items for detail in item.missing_information))
            conflicts = list(dict.fromkeys(detail for item in category_items for detail in item.conflicts))
            notes = list(
                dict.fromkeys(note for item in category_items for note in item.additional_notes if note != "Not Available")
            ) or ["Not Available"]
            actions = list(dict.fromkeys(action for item in category_items for action in item.recommended_actions))
            issue = self._combine_issue_phrases(base.category.value, phrases)

            consolidated.append(
                base.model_copy(
                    update={
                        "issue": issue,
                        "evidence": evidence[:5],
                        "images": images,
                        "recommended_actions": actions,
                        "additional_notes": notes,
                        "missing_information": missing,
                        "conflicts": conflicts,
                    }
                )
            )
        return consolidated

    def _short_issue_phrase(self, issue: str) -> str:
        text = issue.strip()
        lowered = text.lower()
        replacements = (
            "negative side description",
            "positive side description",
            "observed",
            "condition of",
        )
        for token in replacements:
            lowered = lowered.replace(token, "")
        lowered = " ".join(lowered.split())

        if "damp" in lowered:
            if "skirting" in lowered:
                return "dampness at skirting level"
            if "ceiling" in lowered:
                return "dampness at ceiling"
            if "efflorescence" in lowered:
                return "dampness with efflorescence"
            return "dampness"
        if "leak" in lowered:
            if "parking" in lowered and "ceiling" in lowered:
                return "leakage at parking ceiling"
            if "adjacent wall" in lowered:
                return "leakage at adjacent walls"
            if "interior" in lowered:
                return "leakage at interior side"
            if "wc" in lowered or "bath" in lowered:
                return "internal wet-area leakage"
            if "plumbing" in lowered:
                return "possible plumbing-related leakage"
            return "leakage"
        if "hollow" in lowered:
            return "tile hollowness"
        if "crack" in lowered:
            if "external wall" in lowered:
                return "external wall cracks"
            if "beam" in lowered or "column" in lowered:
                return "cracks in RCC members"
            return "cracks"
        if "spalling" in lowered or "corrosion" in lowered:
            return "corrosion or spalling of concrete"
        return text[:80]

    def _combine_issue_phrases(self, category: str, phrases: list[str]) -> str:
        unique_phrases = list(dict.fromkeys(phrases))
        if not unique_phrases:
            return "Not Available"
        if len(unique_phrases) == 1:
            return unique_phrases[0].capitalize()
        if category == "leakage":
            return f"Multiple leakage indicators: {', '.join(unique_phrases[:4])}"
        if category == "dampness":
            return f"Multiple dampness indicators: {', '.join(unique_phrases[:4])}"
        if category == "crack":
            return f"Multiple crack indicators: {', '.join(unique_phrases[:4])}"
        if category == "structural":
            return f"Multiple structural distress indicators: {', '.join(unique_phrases[:4])}"
        return "; ".join(unique_phrases[:4])
