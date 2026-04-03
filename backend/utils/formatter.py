from __future__ import annotations

from pathlib import Path

from backend.models import StructuredReport

DEFAULT_TEMPLATE = """# Detailed Diagnosis Report

## SECTION 1 INTRODUCTION
### 1.1 Background
This report has been generated from the available inspection and thermal input documents to summarize observed defects, likely causes, and suggested next actions.

### 1.2 Objective of the Health Assessment
To identify visible issues, correlate supporting evidence, prioritize action areas, and present a structured client-ready diagnostic summary.

### 1.3 Scope of This Report
The output is limited to the information available in the provided inspection and thermal inputs. Missing or unclear data has been explicitly marked.

## SECTION 2 GENERAL INFORMATION
### 2.1 Property Issue Summary
{{summary}}

### 2.2 Description of Site
{{site_description}}

## SECTION 3 VISUAL OBSERVATION AND READINGS
### 3.1 Summary of Key Observations
{{observation_summary}}

### 3.2 Area-wise Observations
{{area_observations}}

## SECTION 4 ANALYSIS & SUGGESTIONS
### 4.1 Probable Root Cause
{{root_cause}}

### 4.2 Severity Assessment
{{severity}}

### 4.3 Actions Required & Suggested Therapies
{{actions}}

### 4.4 Additional Notes
{{notes}}

### 4.5 Consolidated Summary Table
{{summary_table}}

## SECTION 5 LIMITATION AND PRECAUTION NOTE
{{missing_info}}
"""


def render_markdown_report(report: StructuredReport, template_path: str | Path | None = None) -> str:
    template = _load_template(template_path)
    replacements = {
        "{{summary}}": report.property_issue_summary,
        "{{site_description}}": _build_site_description(report),
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


def _build_site_description(report: StructuredReport) -> str:
    areas = [
        _normalize_area_label(entry["area"])
        for entry in report.area_wise_observations
        if entry["area"] != "Not Available"
    ]
    if not areas:
        return "Site description is Not Available in the provided source inputs."
    return (
        "The primary affected zones identified from the provided inputs include "
        f"{', '.join(areas)}. The report below consolidates the visible inspection findings "
        "and any supporting thermal references available."
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
        blocks.append(f"#### 3.2.{index} {area}")
        for observation in entry["observations"]:
            blocks.append(f"- Observation: {observation['issue']}")
            blocks.append(f"- Category: {observation['category'].replace('_', ' ').title()}")
            blocks.append(f"- Source: {observation['source'].title()}")
            blocks.append(f"- Supporting Evidence: {', '.join(observation['evidence']) or 'Not Available'}")
            if observation["images"] and observation["images"][0] != "Image Not Available":
                blocks.append("- Visual Reference:")
                for image in observation["images"][:2]:
                    blocks.append(f"  ![]({image})")
            else:
                blocks.append("- Visual Reference: Image Not Available")
            if observation["conflicts"]:
                blocks.append(f"- Conflict Note: {', '.join(observation['conflicts'])}")
            if observation["missing_information"]:
                blocks.append(f"- Missing / Unclear: {', '.join(observation['missing_information'])}")
            blocks.append("")
    return "\n".join(blocks).strip() or "Not Available"


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
