from __future__ import annotations

from collections import defaultdict
import re

from backend.models import EnrichedObservation, GeneralInformation, ParsedBundle, StructuredReport
from backend.services.llm_service import LLMService


class StructuringAgent:
    """Step 4: format enriched observations into the DDR template structure."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    def run(self, observations: list[EnrichedObservation], bundle: ParsedBundle | None = None) -> StructuredReport:
        if self.llm_service.is_configured():
            try:
                return self._run_with_llm(observations, bundle)
            except Exception:
                pass
        return self._run_with_rules(observations, bundle)

    def _run_with_llm(self, observations: list[EnrichedObservation], bundle: ParsedBundle | None = None) -> StructuredReport:
        general_information = self._extract_general_information(bundle)
        response = self.llm_service.generate_json(
            task_name="structuring_agent",
            instructions=(
                "Convert the enriched observations into the final DDR structure.\n"
                "You must produce a richly detailed, client-friendly, paragraph-style report.\n"
                "The report must contain these top-level fields:\n"
                "- general_information\n"
                "- property_issue_summary\n"
                "- area_wise_observations\n"
                "- probable_root_cause\n"
                "- severity_assessment\n"
                "- recommended_actions\n"
                "- additional_notes\n"
                "- missing_or_unclear_information\n"
                "Rules:\n"
                "- general_information must include customer_name_unit, site_address, type_of_structure_and_age, date_of_inspection\n"
                "- area_wise_observations must cover all supported impacted areas and flagged structural elements when present\n"
                "- each observation entry should prefer narrative writing and may include these keys when useful:\n"
                "  issue, narrative, negative_side, positive_side, category, source, images, thermal_images, visual_images, thermal_caption, visual_caption, evidence, probable_root_cause, severity, severity_reasoning, recommended_actions, additional_notes, conflicts, missing_information\n"
                "- write complete paragraphs, not field dumps\n"
                "- preserve only relevant images under the correct area observation\n"
                "- do not invent metadata or temperatures; use 'Not Available' when missing\n"
                "- deduplicate repeated checklist noise into one stronger narrative per area/issue\n"
                "Return JSON matching the structured report format."
            ),
            payload={
                "general_information_hint": general_information.model_dump(),
                "inspection_file_name": bundle.inspection.file_name if bundle else "Not Available",
                "inspection_text_sample": (bundle.inspection.full_text[:12000] if bundle else "Not Available"),
                "thermal_text_sample": (bundle.thermal.full_text[:8000] if bundle else "Not Available"),
                "observations": [item.model_dump() for item in observations],
            },
        )
        return StructuredReport.model_validate(response)

    def _run_with_rules(self, observations: list[EnrichedObservation], bundle: ParsedBundle | None = None) -> StructuredReport:
        grouped: dict[str, list[EnrichedObservation]] = defaultdict(list)
        for observation in observations:
            grouped[observation.area].append(observation)

        general_information = self._extract_general_information(bundle)
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
                            "narrative": self._build_area_narrative(item),
                            "negative_side": item.issue,
                            "positive_side": self._infer_positive_side(item),
                            "category": item.category.value,
                            "source": item.source.value,
                            "images": item.images or ["Image Not Available"],
                            "thermal_images": [image for image in item.images if "thermal" in image.lower()],
                            "visual_images": [image for image in item.images if "inspection" in image.lower()],
                            "thermal_caption": self._build_image_caption("THERMAL REFERENCE", area, item.issue),
                            "visual_caption": self._build_image_caption("VISUAL REFERENCE", area, self._infer_positive_side(item)),
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
            general_information=general_information,
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

    def _extract_general_information(self, bundle: ParsedBundle | None) -> GeneralInformation:
        if not bundle:
            return GeneralInformation()
        text = bundle.inspection.full_text
        return GeneralInformation(
            customer_name_unit=self._search_value(text, [r"Customer Name\s*[:\-]\s*(.+)", r"Customer Name\s+(.+)"]),
            site_address=self._search_value(text, [r"Address\s*[:\-]\s*(.+)", r"Site Address\s*[:\-]\s*(.+)"]),
            type_of_structure_and_age=self._build_structure_age(text),
            date_of_inspection=self._search_value(text, [r"Inspection Date and Time\s*[:\-]\s*(.+)", r"Inspection Date\s*[:\-]\s*(.+)"]),
        )

    def _search_value(self, text: str, patterns: list[str]) -> str:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = " ".join(match.group(1).split())
                value = re.split(r"(Email|Mobile|Address|Property Age|Property Type|Floors)", value, maxsplit=1)[0].strip(" |,;")
                if value:
                    return value
        return "Not Available"

    def _build_structure_age(self, text: str) -> str:
        property_type = self._search_value(text, [r"Property Type\s*[:\-]\s*(.+)"])
        property_age = self._search_value(text, [r"Property Age \(In years\)\s*[:\-]\s*(.+)", r"Property Age\s*[:\-]\s*(.+)"])
        if property_type == "Not Available" and property_age == "Not Available":
            return "Not Available"
        if property_age == "Not Available":
            return property_type
        if property_type == "Not Available":
            return f"{property_age} years old"
        return f"{property_type} | {property_age} years old"

    def _build_area_narrative(self, item: EnrichedObservation) -> str:
        area = item.area if item.area != "Not Available" else "the affected area"
        issue = item.issue or "visible damage"
        positive_side = self._infer_positive_side(item)
        temp_text = " Thermal support is available from the submitted infrared report." if item.thermal_support else ""
        source_clause = (
            f" Based on the combined review, this negative-side distress appears to be linked to {positive_side}."
            if positive_side != "Not Available"
            else " The exact positive-side source could not be confirmed from the available records."
        )
        return (
            f"During our inspection of {area}, we observed {issue}.{temp_text}"
            f"{source_clause} This interpretation is based on the inspection evidence and the related supporting references available in the source documents."
        )

    def _infer_positive_side(self, item: EnrichedObservation) -> str:
        for evidence in item.evidence:
            if evidence.lower().startswith("positive side:"):
                value = evidence.split(":", 1)[1].strip()
                if value:
                    return value
        evidence_text = " ".join(item.evidence).lower()
        if "tile joint" in evidence_text or "gap" in evidence_text:
            return "open or deteriorated tile joints on the exposed side"
        if "plumbing" in evidence_text or "pipe" in evidence_text or "trap" in evidence_text:
            return "a plumbing-related defect on the exposed side"
        if "external wall" in evidence_text or "crack" in evidence_text:
            return "cracks or openings at the exposed side"
        if "hollow" in evidence_text:
            return "tile hollowness and debonding at the exposed side"
        return "Not Available"

    def _build_image_caption(self, label: str, area: str, description: str) -> str:
        text = (description or "Not Available").upper()
        return f"{label} - {area.upper()}: {text}"

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
