from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.models import StructuredReport


class PDFService:
    def __init__(self) -> None:
        self.styles = self._build_styles()

    def render_report(
        self,
        report: StructuredReport,
        output_path: str | Path,
        report_title: str = "Detailed Diagnosis Report",
        subject_name: str = "Client Property",
    ) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(output),
            pagesize=A4,
            leftMargin=1.5 * cm,
            rightMargin=1.5 * cm,
            topMargin=1.5 * cm,
            bottomMargin=1.5 * cm,
        )

        story = []
        story.extend(self._build_cover(report_title, subject_name))
        story.extend(self._build_sections(report))
        doc.build(story, onFirstPage=self._draw_page_frame, onLaterPages=self._draw_page_frame)
        return output

    def _build_cover(self, report_title: str, subject_name: str) -> list:
        return [
            Spacer(1, 2.5 * cm),
            Paragraph("UrbanRoof Style DDR", self.styles["brand"]),
            Spacer(1, 0.3 * cm),
            Paragraph(report_title, self.styles["cover_title"]),
            Spacer(1, 0.4 * cm),
            Paragraph(subject_name, self.styles["cover_subject"]),
            Spacer(1, 0.8 * cm),
            Paragraph(
                "Prepared from inspection and thermal documents using the AI DDR pipeline.",
                self.styles["body"],
            ),
            Spacer(1, 1.0 * cm),
            Paragraph("Confidential Diagnostic Report", self.styles["tag"]),
            PageBreak(),
        ]

    def _build_sections(self, report: StructuredReport) -> list:
        story: list = []
        story.extend(
            [
                Paragraph("SECTION 1  GENERAL INFORMATION", self.styles["section"]),
                Paragraph("1.1 Client and Site Details", self.styles["subsection"]),
                Paragraph(
                    f"<b>Customer Name / Unit:</b> {report.general_information.customer_name_unit}<br/>"
                    f"<b>Site Address:</b> {report.general_information.site_address}<br/>"
                    f"<b>Type of Structure & Age:</b> {report.general_information.type_of_structure_and_age}<br/>"
                    f"<b>Date of Inspection:</b> {report.general_information.date_of_inspection}",
                    self.styles["body"],
                ),
                Paragraph("1.2 Background", self.styles["subsection"]),
                Paragraph(
                    "This report consolidates the available site inspection findings and supporting thermal references into a client-ready diagnostic summary.",
                    self.styles["body"],
                ),
                Paragraph("1.3 Objective of the Health Assessment", self.styles["subsection"]),
                Paragraph(
                    "To identify visible distress, correlate related evidence, assess likely seriousness, and outline recommended next actions.",
                    self.styles["body"],
                ),
                Paragraph("1.4 Scope of Work", self.styles["subsection"]),
                Paragraph(
                    "This report is limited to the information present in the provided inspection and thermal source documents. Missing or unclear information has been explicitly marked.",
                    self.styles["body"],
                ),
                Spacer(1, 0.25 * cm),
                Paragraph("SECTION 2  PROPERTY ISSUE SUMMARY", self.styles["section"]),
                Paragraph("2.1 Executive Brief", self.styles["subsection"]),
                Paragraph(report.property_issue_summary, self.styles["body"]),
                Spacer(1, 0.25 * cm),
                Paragraph("SECTION 3  AREA-WISE AND STRUCTURAL OBSERVATIONS", self.styles["section"]),
                Paragraph("3.1 Summary", self.styles["subsection"]),
            ]
        )

        for area_entry in report.area_wise_observations:
            area = self._normalize_area(area_entry["area"])
            obs_list = [obs["issue"] for obs in area_entry["observations"] if obs["issue"] != "Not Available"]
            if obs_list:
                story.append(Paragraph(f"{area}: {', '.join(obs_list)}", self.styles["bullet"]))

        story.append(Paragraph("3.2 Area-wise Observations", self.styles["subsection"]))
        for idx, area_entry in enumerate(report.area_wise_observations, start=1):
            area = self._normalize_area(area_entry["area"])
            story.append(Paragraph(f"3.2.{idx} {area}", self.styles["minor_heading"]))
            for observation in area_entry["observations"]:
                story.append(Paragraph(observation.get("narrative") or self._fallback_narrative(area, observation), self.styles["body"]))
                story.extend(
                    self._build_images(
                        observation.get("thermal_images") or [],
                        observation.get("thermal_caption") or "THERMAL REFERENCE - NOT AVAILABLE",
                    )
                )
                story.extend(
                    self._build_images(
                        observation.get("visual_images") or [],
                        observation.get("visual_caption") or "VISUAL REFERENCE - NOT AVAILABLE",
                    )
                )
                if observation.get("missing_information"):
                    story.append(
                        Paragraph(
                            f"<b>Missing / Unclear:</b> {', '.join(observation['missing_information'])}",
                            self.styles["body_small"],
                        )
                    )
                story.append(Spacer(1, 0.18 * cm))

        story.extend(
            [
                Paragraph("SECTION 4  PROBABLE ROOT CAUSE", self.styles["section"]),
                Paragraph(report.probable_root_cause, self.styles["body"]),
                Paragraph("SECTION 5  DYNAMIC SEVERITY ASSESSMENT", self.styles["section"]),
                *[Paragraph(line, self.styles["body"]) for line in report.severity_assessment.splitlines() if line.strip()],
                Paragraph("SECTION 6  SUGGESTED THERAPIES AND RECOMMENDED ACTIONS", self.styles["section"]),
                *[Paragraph(item, self.styles["body"]) for item in report.recommended_actions],
                Paragraph("SECTION 7  LIMITATIONS AND PRECAUTION NOTE", self.styles["section"]),
                *[Paragraph(item, self.styles["body"]) for item in report.additional_notes],
                Paragraph("SECTION 8  SUMMARY TABLE", self.styles["section"]),
                self._build_summary_table(report),
                Spacer(1, 0.2 * cm),
                Paragraph("SECTION 9  MISSING OR UNCLEAR INFORMATION", self.styles["section"]),
                *[Paragraph(item, self.styles["body"]) for item in report.missing_or_unclear_information],
            ]
        )
        return story

    def _build_images(self, image_paths: list[str], caption: str) -> list:
        valid_paths = [path for path in image_paths if path != "Image Not Available"]
        if not valid_paths:
            return [Paragraph("Image Not Available", self.styles["body_small"])]

        blocks: list = [Paragraph(caption, self.styles["body_small"])]
        row = []
        for image_path in valid_paths[:2]:
            local_path = image_path.replace("/", "\\")
            if local_path.startswith("http"):
                blocks.append(Paragraph(image_path, self.styles["body_small"]))
                continue
            path = Path(local_path)
            if not path.exists():
                blocks.append(Paragraph("Image Not Available", self.styles["body_small"]))
                continue
            row.append(Image(str(path), width=7.2 * cm, height=5.2 * cm))
        if row:
            blocks.append(Table([row], colWidths=[8 * cm] * len(row), hAlign="LEFT"))
        return blocks

    def _fallback_narrative(self, area: str, observation: dict) -> str:
        negative_side = observation.get("negative_side") or observation.get("issue", "Not Available")
        positive_side = observation.get("positive_side") or "Not Available"
        if positive_side == "Not Available":
            return (
                f"During our inspection of {area}, we observed {negative_side}. "
                "The exact exposed-side source could not be confirmed from the available records."
            )
        return (
            f"During our inspection of {area}, we observed {negative_side}. "
            f"Based on the correlated records, this condition appears to be linked to {positive_side}."
        )

    def _build_summary_table(self, report: StructuredReport) -> Table:
        rows = [["Area", "Observation", "Category", "Severity"]]
        for area_entry in report.area_wise_observations:
            area = self._normalize_area(area_entry["area"])
            for observation in area_entry["observations"]:
                rows.append(
                    [
                        area,
                        observation["issue"],
                        observation["category"].replace("_", " ").title(),
                        observation["severity"].title(),
                    ]
                )
        table = Table(rows, colWidths=[3.5 * cm, 7.3 * cm, 3.0 * cm, 2.5 * cm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b5b")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d1dc")),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("LEADING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    def _site_description(self, report: StructuredReport) -> str:
        areas = [self._normalize_area(entry["area"]) for entry in report.area_wise_observations]
        return (
            "The main affected areas identified from the submitted documents include "
            + ", ".join(areas)
            + ". The report below prioritizes visible issues and supporting thermal references relevant to those areas."
        )

    def _normalize_area(self, area: str) -> str:
        return {"Wc": "WC / Wet Area", "Not Available": "Unmapped Thermal Reference"}.get(area, area)

    def _build_styles(self):
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                name="brand",
                fontName="Helvetica-Bold",
                fontSize=14,
                textColor=colors.HexColor("#8a6f3b"),
                alignment=TA_CENTER,
                spaceAfter=10,
            )
        )
        styles.add(
            ParagraphStyle(
                name="cover_title",
                fontName="Helvetica-Bold",
                fontSize=24,
                textColor=colors.HexColor("#1f3b5b"),
                alignment=TA_CENTER,
                leading=28,
            )
        )
        styles.add(
            ParagraphStyle(
                name="cover_subject",
                fontName="Helvetica",
                fontSize=12,
                textColor=colors.HexColor("#516173"),
                alignment=TA_CENTER,
                spaceAfter=14,
            )
        )
        styles.add(
            ParagraphStyle(
                name="tag",
                fontName="Helvetica-Bold",
                fontSize=10,
                textColor=colors.white,
                backColor=colors.HexColor("#1f3b5b"),
                alignment=TA_CENTER,
                borderPadding=(5, 8, 5),
            )
        )
        styles.add(
            ParagraphStyle(
                name="section",
                fontName="Helvetica-Bold",
                fontSize=14,
                textColor=colors.HexColor("#1f3b5b"),
                spaceBefore=10,
                spaceAfter=8,
            )
        )
        styles.add(
            ParagraphStyle(
                name="subsection",
                fontName="Helvetica-Bold",
                fontSize=11,
                textColor=colors.HexColor("#26384a"),
                spaceBefore=8,
                spaceAfter=4,
            )
        )
        styles.add(
            ParagraphStyle(
                name="minor_heading",
                fontName="Helvetica-Bold",
                fontSize=10,
                textColor=colors.HexColor("#3a536f"),
                spaceBefore=8,
                spaceAfter=4,
            )
        )
        styles.add(
            ParagraphStyle(
                name="body",
                fontName="Helvetica",
                fontSize=9.2,
                leading=13,
                textColor=colors.HexColor("#1f2937"),
                spaceAfter=4,
            )
        )
        styles.add(
            ParagraphStyle(
                name="body_small",
                fontName="Helvetica",
                fontSize=8.2,
                leading=11,
                textColor=colors.HexColor("#3f4f60"),
                spaceAfter=3,
            )
        )
        styles.add(
            ParagraphStyle(
                name="bullet",
                fontName="Helvetica",
                fontSize=9,
                leading=12,
                leftIndent=12,
                bulletIndent=0,
                spaceAfter=3,
            )
        )
        return styles

    def _draw_page_frame(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d4dbe3"))
        canvas.setLineWidth(0.6)
        canvas.line(doc.leftMargin, A4[1] - 1.2 * cm, A4[0] - doc.rightMargin, A4[1] - 1.2 * cm)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(colors.HexColor("#1f3b5b"))
        canvas.drawString(doc.leftMargin, A4[1] - 0.9 * cm, "Detailed Diagnosis Report")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawRightString(A4[0] - doc.rightMargin, 0.9 * cm, f"Page {doc.page}")
        canvas.restoreState()
