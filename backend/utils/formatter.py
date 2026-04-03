from __future__ import annotations

from pathlib import Path

from backend.models import StructuredReport

DEFAULT_TEMPLATE = """# Detailed Diagnosis Report

## 1. General Information
{{general_information}}

## 2. Property Issue Summary
{{summary}}

## 3. Summary of Key Observations
{{observation_summary}}

## 4. Area-wise and Structural Observations
{{area_observations}}

## 5. Probable Root Cause
{{root_cause}}

## 6. Dynamic Severity Assessment
{{severity}}

## 7. Suggested Therapies and Recommended Actions
{{actions}}

## 8. Limitations and Precaution Note
{{notes}}

## 9. Consolidated Summary Table
{{summary_table}}

## 10. Missing or Unclear Information
{{missing_info}}
"""


def render_markdown_report(report: StructuredReport, template_path: str | Path | None = None) -> str:
    template = _load_template(template_path)
    replacements = {
        "{{general_information}}": _format_general_information(report),
        "{{summary}}": report.property_issue_summary,
        "{{observation_summary}}": _build_observation_summary(report),
        "{{area_observations}}": _format_area_observations(report.area_wise_observations),
        "{{root_cause}}": report.probable_root_cause,
        "{{severity}}": report.severity_assessment,
        "{{actions}}": _format_list(report.recommended_actions),
        "{{notes}}": _format_list(report.additional_notes),
        "{{summary_table}}": _format_summary_table(report.area_wise_observations),
        "{{missing_info}}": _format_list(report.missing_or_unclear_information),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


def _load_template(template_path: str | Path | None) -> str:
    if template_path is None:
        template_path = Path(__file__).resolve().parents[2] / "templates" / "ddr_template.md"
    path = Path(template_path)
    if not path.exists():
        return DEFAULT_TEMPLATE
    return path.read_text(encoding="utf-8")


def _format_general_information(report: StructuredReport) -> str:
    info = report.general_information
    return "\n".join(
        [
            f"- Customer Name / Unit: {info.customer_name_unit}",
            f"- Site Address: {info.site_address}",
            f"- Type of Structure & Age: {info.type_of_structure_and_age}",
            f"- Date of Inspection: {info.date_of_inspection}",
        ]
    )


def _build_observation_summary(report: StructuredReport) -> str:
    lines: list[str] = []
    for entry in report.area_wise_observations:
        area = _normalize_area_label(entry["area"])
        issues = [obs["issue"] for obs in entry["observations"] if obs["issue"] != "Not Available"]
        if not issues:
            continue
        lines.append(f"- {area}: {', '.join(issues)}")
    return "\n".join(lines) if lines else "- Not Available"


def _format_area_observations(entries: list[dict]) -> str:
    blocks: list[str] = []
    for index, entry in enumerate(entries, start=1):
        area = _normalize_area_label(entry["area"])
        blocks.append(f"### 4.{index} {area}")
        for observation in entry["observations"]:
            narrative = observation.get("narrative") or _fallback_narrative(area, observation)
            blocks.append(narrative)
            thermal_images = observation.get("thermal_images") or []
            visual_images = observation.get("visual_images") or []
            if thermal_images:
                for idx2, image in enumerate(thermal_images[:2], start=1):
                    blocks.append(f"*IMAGE {idx2}: {observation.get('thermal_caption', 'THERMAL REFERENCE - NOT AVAILABLE')}*")
                    blocks.append(f"![]({image})")
            else:
                blocks.append("Image Not Available.")
            if visual_images:
                for idx2, image in enumerate(visual_images[:2], start=1):
                    blocks.append(f"*IMAGE {idx2}: {observation.get('visual_caption', 'VISUAL REFERENCE - NOT AVAILABLE')}*")
                    blocks.append(f"![]({image})")
            elif not thermal_images:
                blocks.append("Image Not Available.")
            if observation["conflicts"]:
                blocks.append(f"Conflict Note: {', '.join(observation['conflicts'])}")
            if observation["missing_information"]:
                blocks.append(f"Missing / Unclear: {', '.join(observation['missing_information'])}")
            blocks.append("")
    return "\n".join(blocks).strip() or "Not Available"


def _fallback_narrative(area: str, observation: dict) -> str:
    negative_side = observation.get("negative_side") or observation.get("issue", "Not Available")
    positive_side = observation.get("positive_side") or "Not Available"
    if positive_side == "Not Available":
        return (
            f"During our inspection of {area}, we observed {negative_side}. "
            "The exact exposed-side source could not be established from the available records, "
            "so it has been marked as Not Available."
        )
    return (
        f"During our inspection of {area}, we observed {negative_side}. "
        f"This condition appears to be linked to {positive_side}, based on the correlated source records and supporting references."
    )


def _format_summary_table(entries: list[dict]) -> str:
    lines = [
        "| Area | Observation | Category | Severity |",
        "| --- | --- | --- | --- |",
    ]
    for entry in entries:
        area = _normalize_area_label(entry["area"])
        for observation in entry["observations"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        area,
                        _escape_cell(observation["issue"]),
                        observation["category"].replace("_", " ").title(),
                        observation["severity"].title(),
                    ]
                )
                + " |"
            )
    return "\n".join(lines) if len(lines) > 2 else "Not Available"


def _format_list(items: list[str]) -> str:
    if not items:
        return "- Not Available"
    return "\n".join(f"- {item}" for item in items)


def _escape_cell(value: str) -> str:
    return value.replace("|", "/")


def _normalize_area_label(area: str) -> str:
    mapping = {
        "Wc": "WC / Wet Area",
        "Hall": "Hall",
        "Bathroom": "Bathroom",
        "Parking": "Parking",
        "Master Bedroom": "Master Bedroom",
        "Common Bathroom": "Common Bathroom",
    }
    return mapping.get(area, area)
