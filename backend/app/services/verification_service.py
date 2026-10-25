"""
Developer 2 - Verification Service.
Ensures the LLM is not hallucinating numbers, and turns that check into a confidence score.

Two independent signals feed the score:
  * Number traceability  - what fraction of the numbers in the report came from a tool result.
  * Evidence completeness - sample volume, data freshness, and incident/event overlap.

The score is a weighted blend of both, so a report whose numbers all check out but which
rests on 12 samples cannot score higher than one backed by a month of good data.
"""
import re
from typing import Any, List, Tuple

from app.models.schemas import ToolCall, VerificationResult, VerificationStep

# Weights for the two signals. The number-traceability term is weighted highest because a
# hallucinated figure is the failure mode that matters most: it silently changes a decision.
TRACEABILITY_WEIGHT = 0.60
EVIDENCE_WEIGHT = 0.40


class VerificationService:
    def __init__(self):
        # Matches decimals, integers, and common units.
        # The unit group is CAPTURING on purpose: findall() then yields (value, unit) pairs.
        # With a non-capturing unit group it yields bare strings, and unpacking a string like
        # "100" into two names raises ValueError on any number of two digits or more.
        self.number_pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*(m|MiB|GiB|USD|\$|%|vCPU|core)?",
            re.IGNORECASE
        )

    def verify_report(self, report_text: str, investigation_log: List[ToolCall]) -> VerificationResult:
        """
        Extracts numbers from report and verifies they exist in the tool results.
        Returns a score based on the verification ratio.
        """
        matches = self.number_pattern.findall(report_text)
        if not matches:
            return VerificationResult(is_valid=True, verified_count=0, unverified_count=0)

        verified_count = 0
        unverified_count = 0
        errors = []
        verification_steps = []

        log_content = str(investigation_log).lower()

        for value, unit in matches:
            full_value = f"{value}{unit}".lower()

            if full_value in log_content or value in log_content:
                verified_count += 1
                verification_steps.append(VerificationStep(
                    claimed_value=full_value,
                    status="verified"
                ))
            else:
                unverified_count += 1
                errors.append(f"Unverified value found in report: {full_value}")
                verification_steps.append(VerificationStep(
                    claimed_value=full_value,
                    status="unverified"
                ))

        return VerificationResult(
            is_valid=unverified_count == 0,
            errors=errors,
            verified_count=verified_count,
            unverified_count=unverified_count
        )

    def calculate_confidence_score(self, verification: VerificationResult) -> float:
        """Traceability-only score: verified numbers / total numbers, as a percentage.

        A report with no numbers at all returns 100.0: there is nothing to misstate. This is
        deliberately not the same as the blended score below, which also weighs evidence quality.
        """
        total = verification.verified_count + verification.unverified_count
        if total == 0:
            return 100.0
        return round((verification.verified_count / total) * 100, 2)

    def score_confidence(
        self,
        verification: VerificationResult,
        *,
        sample_count: int = 0,
        required_samples: int = 1,
        age_hours: float | None = None,
        max_age_hours: float = 72.0,
        risk_overlap: bool = False,
        blocking_objections: int = 0,
        advisory_objections: int = 0,
    ) -> tuple[float, str]:
        """Blend number traceability with evidence quality into one 0-100 confidence score.

        Returns (score, basis) where `basis` is a one-line explanation of the score, so the UI
        never shows a number the reviewer cannot interrogate.

        Objections scale the penalty: one advisory note is a small dent, three blocking objections
        are a serious one. A flat penalty would make every risky workload look equally uncertain
        and destroy the score's ability to rank opportunities.
        """
        traceability = self.calculate_confidence_score(verification)

        # Sample sufficiency: full credit at or above the required count, proportional below it.
        required = max(1, required_samples)
        sufficiency = min(100.0, 100.0 * sample_count / required) if sample_count else 0.0

        # Freshness: linear decay to zero at the age limit, 100 when the newest sample is current.
        if age_hours is None:
            freshness = 0.0
        else:
            freshness = max(0.0, min(100.0, 100.0 * (1.0 - age_hours / max(max_age_hours, 1e-9))))

        # Overlap with a known incident or event is a signal to distrust a "safe to shrink" claim.
        overlap_penalty = 30.0 if risk_overlap else 0.0

        # Objection penalty: 12 points per blocking objection, 4 per advisory, capped at 45.
        objection_penalty = min(45.0, 12.0 * blocking_objections + 4.0 * advisory_objections)

        evidence = (0.45 * sufficiency + 0.35 * freshness + 0.20 * (0.0 if risk_overlap else 100.0))
        score = TRACEABILITY_WEIGHT * traceability + EVIDENCE_WEIGHT * evidence
        score -= overlap_penalty + objection_penalty
        score = round(max(0.0, min(100.0, score)), 1)

        basis_parts = [f"{traceability:.1f}% of reported numbers traced to a tool result",
                       f"{sample_count}/{required} samples",
                       f"{'stale' if freshness < 50 else 'fresh'} metrics"]
        if risk_overlap:
            basis_parts.append("incident/event overlap")
        if blocking_objections:
            basis_parts.append(f"{blocking_objections} blocking objection(s)")
        if advisory_objections:
            basis_parts.append(f"{advisory_objections} advisory note(s)")
        return score, "; ".join(basis_parts) + "."

    def evidence_trail(self, investigation_log: List[ToolCall]) -> List[str]:
        """One line per tool call, so the reviewer can see exactly what the agent looked at."""
        trail: List[str] = []
        for step in investigation_log:
            result = step.result
            if isinstance(result, (list, tuple)):
                summary = f"{len(result)} record(s)"
            elif isinstance(result, dict):
                summary = ", ".join(f"{k}={v}" for k, v in list(result.items())[:4])
            elif result is None:
                summary = "no result"
            else:
                text = str(result)
                summary = text if len(text) <= 120 else text[:117] + "..."
            trail.append(f"{step.tool}({', '.join(f'{k}={v}' for k, v in step.params.items())}) -> {summary}")
        return trail
