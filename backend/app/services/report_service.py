"""Format structured analysis results as a human-readable audit report."""

from app.models.schemas import AnalysisResponse


def render_markdown_report(analysis: AnalysisResponse) -> str:
    summary = analysis.summary
    lines = [
        "# Kubernetes FinOps Agent — Audit report",
        "",
        f"Analysis: `{analysis.analysis_id}`  ",
        f"Generated: {analysis.generated_at.isoformat()}  ",
        f"Mode: {analysis.mode}",
        "",
        "> Recommendation-only report. Savings are illustrative estimates. YAML patches are proposals for human review and are never applied automatically.",
        "",
        "## Summary",
        "",
        "| Workloads | Approved | Deferred | Rejected | Needs review | No change | Approved savings / month |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        (f"| {summary.workloads_evaluated} | {summary.approved} | {summary.deferred} | {summary.rejected} "
         f"| {summary.needs_review} | {summary.no_change} | ${summary.estimated_monthly_savings_usd:.2f} |"),
        "",
    ]
    if analysis.warnings:
        lines.extend(["## Ingestion warnings", "", *[f"- {warning}" for warning in analysis.warnings], ""])
    if any(result.proposal.savings_estimate and not result.proposal.savings_estimate.pricing_available
           for result in analysis.results):
        lines.extend(["Currency pricing is unavailable for one or more proposals; USD savings are not calculated. Relative request changes are reported per workload.", ""])
    if analysis.input_issues:
        lines.extend(["## Input validation", ""])
        lines.extend(
            f"- **{issue.severity.upper()} {issue.code}**"
            f"{f' ({issue.workload_id})' if issue.workload_id else ''}: {issue.message}"
            for issue in analysis.input_issues
        )
        lines.append("")

    for result in analysis.results:
        proposal = result.proposal
        current, proposed, metrics = proposal.current, proposal.proposed, proposal.metrics
        lines.extend([
            f"## {result.workload_id} ({result.namespace})",
            "",
            f"**Decision:** {result.decision.value}  ",
            f"**Risk:** {result.risk_level.value}  ",
            f"**Reason:** {result.reason}",
            "",
            "### Proposal and evidence",
            "",
            "| Resource | Current request | Proposed request |",
            "|---|---:|---:|",
            f"| CPU | {current.cpu_request_millicores} millicores | {proposed.cpu_request_millicores if proposed else 'No change'} millicores |",
            f"| Memory | {current.memory_request_mib} MiB | {proposed.memory_request_mib if proposed else 'No change'} MiB |",
            "",
            (f"Optimizer status: `{proposal.status.value}`. Usage: {metrics.sample_count} samples over "
             f"{metrics.span_hours:.2f} hours; CPU P95/P99 {metrics.cpu_p95}/{metrics.cpu_p99} millicores; "
             f"memory P95/P99 {metrics.memory_p95}/{metrics.memory_p99} MiB. "
             f"P99 reliability threshold met: {'yes' if metrics.p99_reliable else 'no (provisional)'}."),
            (f"Potential monthly savings: ${proposal.estimated_monthly_saving_usd:.2f}; "
             f"approved savings counted in summary: ${result.monthly_savings_estimate_usd:.2f}."
             if proposal.savings_estimate and proposal.savings_estimate.pricing_available else
             f"Relative request allocation reduction: {proposal.savings_estimate.total_request_reduction_pct:.2f}%; "
             "currency savings are unavailable.") if proposal.savings_estimate else
            f"Potential monthly savings estimate: ${proposal.estimated_monthly_saving_usd:.2f}.",
            "",
            (f"Confidence: {proposal.confidence.score:.1f}/100 ({proposal.confidence.label}). "
             f"Priority: {proposal.priority_score:.1f}/100."
             if proposal.confidence and proposal.priority_score is not None else "Confidence and priority were not calculated."),
            "",
            "### Safety checks",
            "",
        ])
        if result.checks:
            lines.extend(f"- **{check.name} [{check.code}] — {check.status.value}:** {check.message}" for check in result.checks)
        else:
            lines.append("- No critic checks were recorded.")
        if proposal.reasons:
            lines.extend(["", "Optimizer reasons:", *[f"- {reason}" for reason in proposal.reasons]])
        if proposal.warnings:
            lines.extend(["", "Proposal warnings:", *[f"- {warning}" for warning in proposal.warnings]])
        if proposal.confidence:
            lines.extend(["", "Confidence factors:"])
            lines.extend(f"- {factor.name}: {factor.score:.1f}/100 × {factor.weight:.0%} — {factor.explanation}"
                         for factor in proposal.confidence.factors)
        if proposal.incident_evidence:
            lines.extend(["", "Matched incident evidence:"])
            lines.extend(f"- {incident.incident_id} ({incident.match_type}, {incident.severity}) — "
                         f"{incident.timestamp.isoformat()}: {incident.description}"
                         for incident in proposal.incident_evidence)
        if proposal.anomalies:
            lines.extend(["", "Usage anomalies:"])
            lines.extend(f"- {anomaly.severity}: {anomaly.explanation}" for anomaly in proposal.anomalies)
        if result.yaml_patch:
            lines.extend(["", "### Proposed Kubernetes patch (review only)", "", "```yaml", result.yaml_patch, "```"])
        lines.append("")

    return "\n".join(lines)
