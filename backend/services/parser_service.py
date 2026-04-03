from __future__ import annotations

import re
from pathlib import Path

import fitz

from backend.models import ExtractedImage, ParsedBundle, ParsedDocument, SourceType


class ParserService:
    """PDF text and visual reference extraction with lightweight area mapping heuristics."""

    AREA_PATTERN = re.compile(
        r"\b(hall|bedroom|kitchen|bathroom|wc|toilet|balcony|parking|living room|master bedroom|common bathroom)\b",
        re.IGNORECASE,
    )

    def __init__(self, image_output_dir: str | Path | None = None) -> None:
        base_dir = Path(image_output_dir) if image_output_dir else Path("artifacts/images")
        self.image_output_dir = base_dir
        self.image_output_dir.mkdir(parents=True, exist_ok=True)

    def parse_bundle(
        self,
        inspection_pdf_path: str | Path,
        thermal_pdf_path: str | Path,
    ) -> ParsedBundle:
        inspection = self.parse_pdf(inspection_pdf_path, SourceType.INSPECTION)
        thermal = self.parse_pdf(thermal_pdf_path, SourceType.THERMAL)
        return ParsedBundle(inspection=inspection, thermal=thermal)

    def parse_pdf(self, pdf_path: str | Path, document_type: SourceType) -> ParsedDocument:
        path = Path(pdf_path)
        doc = fitz.open(path)

        pages: list[str] = []
        images: list[ExtractedImage] = []

        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            page_text = page.get_text("text").strip()
            pages.append(page_text)

            area = self._infer_area(page_text)
            output_path = self._render_page_reference(page, path.stem, page_index + 1, document_type)
            images.append(
                ExtractedImage(
                    id=f"{document_type.value}-{page_index + 1}-page",
                    document_type=document_type,
                    page_number=page_index + 1,
                    path=str(output_path),
                    caption=f"{document_type.value.title()} reference from page {page_index + 1}",
                    mapped_area=area,
                )
            )

        full_text = "\n\n".join(filter(None, pages))
        return ParsedDocument(
            document_type=document_type,
            file_name=path.name,
            full_text=full_text,
            pages=pages,
            images=images,
        )

    def _infer_area(self, text: str) -> str:
        match = self.AREA_PATTERN.search(text or "")
        if not match:
            return "Not Available"
        return match.group(0).title()

    def _render_page_reference(
        self,
        page: fitz.Page,
        stem: str,
        page_number: int,
        document_type: SourceType,
    ) -> Path:
        zoom = 1.6 if document_type == SourceType.INSPECTION else 1.3
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image_name = f"{stem}_p{page_number}_ref.png"
        output_path = self.image_output_dir / image_name
        pixmap.save(output_path)
        return output_path
