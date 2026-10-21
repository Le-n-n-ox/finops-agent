"""Explainable deterministic confidence and opportunity-priority scoring."""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import fmean, pstdev

from app.models.schemas import (
    ConfidenceAssessment,
    ConfidenceFactor,
    DataQualityResult,
    OptimizationProposal,
    PriorityBreakdown,
    UsageAnomaly,
    UsageSummary,
)


def calculate_recommendation_confidence(
    quality: DataQualityResult,
    summary: UsageSummary,
    anomalies: list[UsageAnomaly],
    analysis_time: datetime,
    min_samples: int = 30,
    max_age_hours: float = 24,
    cpu_values: list[float] | None = None,
    memory_values: list[float] | None = None,
    risk_context: bool = False,
) -> ConfidenceAssessment:
    """Score evidence transparently using data validity, freshness, coverage and stability."""
    values = [*(cpu_values or []), *(memory_values or [])]
    if values:
        cv_scores = []
        for series in (cpu_values or [], memory_values or []):
            mean = fmean(series) if series else 0.0
            cv_scores.append(100.0 if len(series) < 2 or mean == 0 else max(0.0, 100.0 - 100.0 * pstdev(series) / mean))
        stability_score = fmean(cv_scores)
    else:
        stability_score = 0.0

    if quality.last_observed_at is None:
        freshness_score = 0.0
    else:
        observed = quality.last_observed_at
        reference = analysis_time
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        age = max(0.0, (reference - observed).total_seconds() / 3600)
        freshness_score = max(0.0, min(100.0, 100.0 * (1.0 - age / max(max_age_hours, 1e-9))))

    anomaly_score = max(0.0, 100.0 - sum(35.0 if a.severity == "high" else 18.0 for a in anomalies))
    factors = [
        ConfidenceFactor(name="validity", score=0.0 if quality.errors or quality.missing_fields else 100.0,
                         weight=0.20, explanation="No validation errors or missing required fields." if not quality.errors and not quality.missing_fields else "Validation errors or missing fields reduce confidence."),
        ConfidenceFactor(name="sample_sufficiency", score=min(100.0, 100.0 * summary.sample_count / max(min_samples, 1)),
                         weight=0.20, explanation=f"{summary.sample_count} observations against a minimum of {min_samples}."),
        ConfidenceFactor(name="freshness", score=freshness_score, weight=0.15,
                         explanation=f"Latest observation age is evaluated against a {max_age_hours:g} hour limit."),
        ConfidenceFactor(name="stability", score=stability_score, weight=0.15,
                         explanation="Score decreases with CPU or memory coefficient of variation."),
        ConfidenceFactor(name="anomalies", score=anomaly_score, weight=0.10,
                         explanation=f"{len(anomalies)} baseline anomaly/anomalies were detected."),
        ConfidenceFactor(name="risk_overlap", score=45.0 if risk_context else 100.0, weight=0.20,
                         explanation="Recent incident or overlapping event context reduces confidence." if risk_context
                         else "No incident or event overlap affects this recommendation."),
    ]
    score = round(sum(factor.score * factor.weight for factor in factors), 1)
    if not quality.usable_for_recommendation:
        score = min(score, 39.0)
    label = "high" if score >= 80 else "medium" if score >= 60 else "low"
    return ConfidenceAssessment(
        score=score,
        label=label,
        factors=factors,
        explanation=f"{label.title()} confidence ({score:.1f}/100) from six weighted, deterministic evidence factors.",
    )


def score_priority(
    recommendation: OptimizationProposal,
    value_score: float,
    confidence_score: float,
) -> tuple[float, PriorityBreakdown]:
    """Rank savings by evidence confidence and explicit operational risk."""
    penalty = min(100.0, sum(20.0 if item.severity == "high" else 10.0 for item in recommendation.anomalies)
                  + sum(20.0 if item.severity.lower() == "high" else 10.0 for item in recommendation.incident_evidence)
                  + sum(20.0 if item.severity.value == "high" else 10.0 for item in recommendation.findings))
    score = round(max(0.0, value_score * confidence_score / 100 / (1 + penalty / 100)), 2)
    breakdown = PriorityBreakdown(
        value_score=round(value_score, 1),
        confidence_score=round(confidence_score, 1),
        risk_penalty=round(penalty, 1),
        explanation="Priority = monthly savings × confidence / 100 ÷ (1 + risk penalty / 100).",
    )
    return score, breakdown
