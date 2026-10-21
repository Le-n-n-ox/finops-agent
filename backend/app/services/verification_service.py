"""
Developer 2 - Verification Service.
Ensures the LLM is not hallucinating numbers.
"""
import re
from typing import Any, List, Tuple
from app.models.schemas import ToolCall, VerificationResult, VerificationStep

class VerificationService:
    def __init__(self):
        # Matches decimals, integers, and common units
        self.number_pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*(?:m|MiB|GiB|USD|\$|%|vCPU|core)?",
            re.IGNORECASE
        )

    def verify_report(self, report_text: str, investigation_log: List[ToolCall]) -> VerificationResult:
        """
        Extracts numbers from report and verifies they exist in the tool results.
        """
        matches = self.number_pattern.findall(report_text)
        if not matches:
            return VerificationResult(is_valid=True, verified_count=0, unverified_count=0)

        verified_count = 0
        unverified_count = 0
        errors = []
        verification_steps = []

        # Convert investigation log to a giant string for simple search
        # In a production system, this would be a more structured lookup
        log_content = str(investigation_log).lower()

        for value, unit in matches:
            full_value = f"{value}{unit}".lower()

            # We look for the number in the log.
            # This is a naive implementation; a better one would check specific tool outputs.
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
