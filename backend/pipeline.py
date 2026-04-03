from __future__ import annotations

from pathlib import Path

from backend.agents.deduplication_agent import DeduplicationAgent
from backend.agents.extraction_agent import ExtractionAgent
from backend.agents.reasoning_agent import ReasoningAgent
from backend.agents.structuring_agent import StructuringAgent
from backend.models import ParsedBundle, ParsedDocument, PipelineResult
from backend.services.parser_service import ParserService
from backend.utils.formatter import render_markdown_report
from backend.models import ObservationCategory


class DDRPipeline:
    def __init__(self) -> None:
        self.parser_service = ParserService()
        self.extraction_agent = ExtractionAgent()
        self.deduplication_agent = DeduplicationAgent()
        self.reasoning_agent = ReasoningAgent()
        self.structuring_agent = StructuringAgent()

    def run(self, inspection_pdf_path: str | Path, thermal_pdf_path: str | Path) -> PipelineResult:
        bundle = self.parser_service.parse_bundle(inspection_pdf_path, thermal_pdf_path)
        return self.run_from_bundle(bundle)

    def run_from_documents(
        self,
        inspection: ParsedDocument,
        thermal: ParsedDocument,
    ) -> PipelineResult:
        return self.run_from_bundle(ParsedBundle(inspection=inspection, thermal=thermal))

    def run_from_bundle(self, bundle: ParsedBundle) -> PipelineResult:
        observations = self.extraction_agent.run(bundle)
        deduplicated = self.deduplication_agent.run(observations)
        deduplicated = self._attach_thermal_supporting_references(deduplicated, bundle)
        enriched = self.reasoning_agent.run(deduplicated)
        structured = self.structuring_agent.run(enriched)
        markdown = render_markdown_report(structured)
        return PipelineResult(
            observations=observations,
            deduplicated_observations=deduplicated,
            enriched_observations=enriched,
            structured_report=structured,
            markdown_report=markdown,
        )

    def _attach_thermal_supporting_references(self, observations, bundle: ParsedBundle):
        candidate_refs = [
            image.path
            for image in bundle.thermal.images
            if image.page_number <= 12
        ]
        candidate_refs = list(dict.fromkeys(candidate_refs))
        ref_index = 0

        updated = []
        for observation in observations:
            if (
                observation.category in {ObservationCategory.DAMPNESS, ObservationCategory.LEAKAGE}
                and ref_index < len(candidate_refs)
            ):
                refs = candidate_refs[ref_index : ref_index + 2]
                ref_index += len(refs)
                images = list(dict.fromkeys(observation.images + refs))
                evidence = list(observation.evidence)
                evidence.append("Supporting thermal reference attached from thermal report.")
                updated.append(
                    observation.model_copy(
                        update={
                            "images": images,
                            "thermal_support": True,
                            "evidence": evidence,
                        }
                    )
                )
            else:
                updated.append(observation)
        return updated
