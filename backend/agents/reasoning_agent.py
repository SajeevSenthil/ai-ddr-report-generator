from __future__ import annotations

from backend.models import EnrichedObservation, Observation, ObservationCategory, SeverityLevel
from backend.services.llm_service import LLMService


class ReasoningAgent:
    """Step 3: infer root cause, severity, and recommended actions from evidence."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    def run(self, observations: list[Observation]) -> list[EnrichedObservation]:
        if self.llm_service.is_configured():
            try:
                return self._run_with_llm(observations)
            except Exception:
                pass
        return [self._rule_based_enrichment(item) for item in observations]

    def _run_with_llm(self, observations: list[Observation]) -> list[EnrichedObservation]:
        response = self.llm_service.generate_json(
            task_name="reasoning_agent",
            instructions=(
                "For each observation, provide evidence-backed analysis only.\n"
                "You must add:\n"
                "- probable_root_cause\n"
                "- severity\n"
                "- severity_reasoning\n"
                "- recommended_actions\n"
                "- additional_notes\n"
                "- conflicts\n"
                "- missing_information\n"
                "Rules:\n"
                "- Do not invent engineering conclusions that are unsupported by the evidence.\n"
                "- Keep thermal findings as supporting evidence unless they clearly indicate a relevant anomaly.\n"
                "- If there is not enough information, write 'Not Available'.\n"
                "- If something is uncertain or conflicting, mention it explicitly.\n"
                "- Recommended actions should be practical and client-friendly.\n"
                "Return JSON with key 'observations'."
            ),
            payload={"observations": [item.model_dump() for item in observations]},
        )
        return [EnrichedObservation.model_validate(item) for item in response.get("observations", [])]

    def _rule_based_enrichment(self, observation: Observation) -> EnrichedObservation:
        category = observation.category
        root_cause = "Not Available"
        actions: list[str] = []
        notes: list[str] = []
        missing: list[str] = []
        conflicts: list[str] = []

        if category == ObservationCategory.DAMPNESS:
            root_cause = "Probable moisture ingress or prolonged water exposure near the affected surface."
            actions = [
                "Inspect adjacent plumbing, waterproofing, and exterior exposure points.",
                "Carry out moisture measurement and open-up inspection before repair.",
            ]
        elif category == ObservationCategory.LEAKAGE:
            root_cause = "Probable active or historical leakage from plumbing joints, wet areas, or exterior envelope."
            actions = [
                "Trace the leakage source through targeted plumbing and waterproofing checks.",
                "Rectify the source before cosmetic restoration.",
            ]
        elif category == ObservationCategory.CRACK:
            root_cause = "Probable movement, shrinkage, or localized structural stress."
            actions = [
                "Assess crack width, pattern, and recurrence.",
                "Refer to a structural engineer if cracks are progressive or wide.",
            ]
        elif category == ObservationCategory.STRUCTURAL:
            root_cause = "Probable substrate deterioration, debonding, or concealed distress."
            actions = [
                "Undertake a detailed condition assessment of the affected assembly.",
                "Repair only after confirming the underlying cause and extent.",
            ]
        elif category == ObservationCategory.THERMAL_ANOMALY:
            root_cause = "Probable temperature variation consistent with moisture retention, voids, or differential material behavior."
            actions = [
                "Correlate thermal anomaly with site inspection and moisture readings.",
                "Confirm whether the anomaly indicates active ingress or a historical condition.",
            ]
            notes.append("Thermal findings are supportive and should be correlated with physical inspection.")
        else:
            missing.append("Probable root cause could not be determined from the available evidence.")
            actions.append("Manual technical review recommended.")

        severity = self._severity_for(category, observation)
        severity_reason = self._severity_reasoning(severity, observation)

        if not observation.images:
            missing.append("Image Not Available")
        if observation.area == "Not Available":
            missing.append("Affected area not clearly stated in source data.")

        return EnrichedObservation(
            **observation.model_dump(),
            probable_root_cause=root_cause,
            severity=severity,
            severity_reasoning=severity_reason,
            recommended_actions=actions or ["Not Available"],
            additional_notes=notes or ["Not Available"],
            conflicts=conflicts,
            missing_information=missing,
        )

    def _severity_for(self, category: ObservationCategory, observation: Observation) -> SeverityLevel:
        text = f"{observation.issue} {' '.join(observation.evidence)}".lower()
        if "severe" in text or "major" in text or category == ObservationCategory.STRUCTURAL:
            return SeverityLevel.HIGH
        if category in {ObservationCategory.LEAKAGE, ObservationCategory.DAMPNESS, ObservationCategory.CRACK}:
            return SeverityLevel.MEDIUM
        if category == ObservationCategory.THERMAL_ANOMALY:
            return SeverityLevel.MEDIUM if observation.thermal_support else SeverityLevel.LOW
        if category == ObservationCategory.OTHER:
            return SeverityLevel.NOT_AVAILABLE
        return SeverityLevel.LOW

    def _severity_reasoning(self, severity: SeverityLevel, observation: Observation) -> str:
        if severity == SeverityLevel.HIGH:
            return "Severity marked high because the issue may indicate structural or persistent concealed damage."
        if severity == SeverityLevel.MEDIUM:
            return "Severity marked medium because the issue may worsen if untreated but available evidence is not critical."
        if severity == SeverityLevel.LOW:
            return "Severity marked low because the observation is limited or supportive rather than a confirmed major defect."
        return "Not Available"
