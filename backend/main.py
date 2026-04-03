from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.models import ExtractedImage, ParsedDocument, SourceType, StructuredReport
from backend.pipeline import DDRPipeline
from backend.services.approval_service import ApprovalService
from backend.services.pdf_service import PDFService
from backend.utils.formatter import render_markdown_report

app = FastAPI(title="AI DDR Report Generator", version="0.1.0")
pipeline = DDRPipeline()
pdf_service = PDFService()
approval_service = ApprovalService()
artifacts_dir = Path("artifacts/images")
artifacts_dir.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(artifacts_dir.parent)), name="artifacts")


class GenerateRequest(BaseModel):
    inspection_pdf_path: str
    thermal_pdf_path: str
    output_markdown_path: str | None = None
    output_json_path: str | None = None


class ImagePayload(BaseModel):
    path: str
    page_number: int = 1
    caption: str = "Image Not Available"
    mapped_area: str = "Not Available"


class RawDocumentPayload(BaseModel):
    file_name: str
    full_text: str
    pages: list[str] = Field(default_factory=list)
    images: list[ImagePayload] = Field(default_factory=list)


class GenerateFromContentRequest(BaseModel):
    inspection: RawDocumentPayload
    thermal: RawDocumentPayload
    output_markdown_path: str | None = None
    output_json_path: str | None = None


class ApprovalRequest(BaseModel):
    property_name: str
    manager_email: str
    client_email: str
    report_url: str
    approve_url: str
    reject_url: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/ddr/generate")
def generate_report(request: GenerateRequest, http_request: Request) -> dict:
    inspection_path = Path(request.inspection_pdf_path)
    thermal_path = Path(request.thermal_pdf_path)

    if not inspection_path.exists():
        raise HTTPException(status_code=400, detail=f"Inspection PDF not found: {inspection_path}")
    if not thermal_path.exists():
        raise HTTPException(status_code=400, detail=f"Thermal PDF not found: {thermal_path}")

    result = pipeline.run(inspection_path, thermal_path)

    if request.output_markdown_path:
        Path(request.output_markdown_path).write_text(result.markdown_report, encoding="utf-8")
    if request.output_json_path:
        Path(request.output_json_path).write_text(
            json.dumps(result.structured_report.model_dump(), indent=2),
            encoding="utf-8",
        )

    pdf_path = _build_pdf_output_path(inspection_path.stem)
    pdf_service.render_report(result.structured_report, pdf_path, subject_name=inspection_path.stem)

    structured_report = _externalize_structured_report(result.structured_report, http_request)
    markdown_report = render_markdown_report(structured_report)

    return {
        "structured_report": structured_report.model_dump(),
        "markdown_report": markdown_report,
        "pdf_path": str(pdf_path),
        "counts": {
            "raw_observations": len(result.observations),
            "deduplicated_observations": len(result.deduplicated_observations),
            "enriched_observations": len(result.enriched_observations),
        },
    }


@app.post("/api/v1/ddr/generate-from-files")
async def generate_report_from_files(
    request: Request,
    inspection_pdf: UploadFile = File(...),
    thermal_pdf: UploadFile = File(...),
) -> dict:
    inspection_suffix = Path(inspection_pdf.filename or "inspection.pdf").suffix or ".pdf"
    thermal_suffix = Path(thermal_pdf.filename or "thermal.pdf").suffix or ".pdf"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        inspection_path = temp_root / f"inspection{inspection_suffix}"
        thermal_path = temp_root / f"thermal{thermal_suffix}"

        inspection_path.write_bytes(await inspection_pdf.read())
        thermal_path.write_bytes(await thermal_pdf.read())

        result = pipeline.run(inspection_path, thermal_path)

    pdf_path = _build_pdf_output_path(inspection_pdf.filename or "inspection.pdf")
    pdf_service.render_report(result.structured_report, pdf_path, subject_name=inspection_pdf.filename or "Inspection")

    structured_report = _externalize_structured_report(result.structured_report, request)
    markdown_report = render_markdown_report(structured_report)

    return {
        "structured_report": structured_report.model_dump(),
        "markdown_report": markdown_report,
        "pdf_path": str(pdf_path),
        "counts": {
            "raw_observations": len(result.observations),
            "deduplicated_observations": len(result.deduplicated_observations),
            "enriched_observations": len(result.enriched_observations),
        },
    }


@app.post("/api/v1/ddr/generate-from-content")
def generate_report_from_content(request: GenerateFromContentRequest, http_request: Request) -> dict:
    inspection = _build_document(request.inspection, SourceType.INSPECTION)
    thermal = _build_document(request.thermal, SourceType.THERMAL)
    result = pipeline.run_from_documents(inspection, thermal)

    if request.output_markdown_path:
        Path(request.output_markdown_path).write_text(result.markdown_report, encoding="utf-8")
    if request.output_json_path:
        Path(request.output_json_path).write_text(
            json.dumps(result.structured_report.model_dump(), indent=2),
            encoding="utf-8",
        )

    pdf_path = _build_pdf_output_path(request.inspection.file_name)
    pdf_service.render_report(result.structured_report, pdf_path, subject_name=request.inspection.file_name)

    structured_report = _externalize_structured_report(result.structured_report, http_request)
    markdown_report = render_markdown_report(structured_report)

    return {
        "structured_report": structured_report.model_dump(),
        "markdown_report": markdown_report,
        "pdf_path": str(pdf_path),
        "counts": {
            "raw_observations": len(result.observations),
            "deduplicated_observations": len(result.deduplicated_observations),
            "enriched_observations": len(result.enriched_observations),
        },
    }


def _build_document(payload: RawDocumentPayload, source_type: SourceType) -> ParsedDocument:
    pages = payload.pages or [payload.full_text]
    images = [
        ExtractedImage(
            id=f"{source_type.value}-{index}",
            document_type=source_type,
            page_number=image.page_number,
            path=image.path,
            caption=image.caption,
            mapped_area=image.mapped_area,
        )
        for index, image in enumerate(payload.images, start=1)
    ]
    return ParsedDocument(
        document_type=source_type,
        file_name=payload.file_name,
        full_text=payload.full_text,
        pages=pages,
        images=images,
    )


def _externalize_structured_report(report: StructuredReport, request: Request) -> StructuredReport:
    updated_entries = []
    for entry in report.area_wise_observations:
        updated_observations = []
        for observation in entry["observations"]:
            updated_images = [
                _externalize_image_path(image, request) for image in observation.get("images", [])
            ] or ["Image Not Available"]
            updated_observations.append({**observation, "images": updated_images})
        updated_entries.append({**entry, "observations": updated_observations})
    return report.model_copy(update={"area_wise_observations": updated_entries})


def _externalize_image_path(path: str, request: Request) -> str:
    if path == "Image Not Available":
        return path
    image_path = Path(path)
    try:
        relative = image_path.relative_to(Path("artifacts"))
    except ValueError:
        return path
    return str(request.base_url).rstrip("/") + "/artifacts/" + str(relative).replace("\\", "/")


def _build_pdf_output_path(source_name: str) -> Path:
    lowered = source_name.lower()
    if "cid01" in lowered:
        name = "final_report_cid01.pdf"
    else:
        stem = Path(source_name).stem or "final_report"
        safe_stem = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in stem)
        name = f"{safe_stem}_final_report.pdf"
    return Path("backend/output") / name


@app.post("/api/v1/ddr/approval-package")
def create_approval_package(request: ApprovalRequest) -> dict:
    package = approval_service.build_package(
        property_name=request.property_name,
        manager_email=request.manager_email,
        client_email=request.client_email,
        report_url=request.report_url,
        approve_url=request.approve_url,
        reject_url=request.reject_url,
    )
    return {
        "manager_email": {
            "to": request.manager_email,
            "subject": package.manager_email_subject,
            "body": package.manager_email_body,
        },
        "client_email": {
            "to": request.client_email,
            "subject": package.client_email_subject,
            "body": package.client_email_body,
        },
    }
