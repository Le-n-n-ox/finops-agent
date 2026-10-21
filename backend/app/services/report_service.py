
"""Format structured analysis results as a human-readable audit report."""

from app.models.schemas import AnalysisResponse


# ... (keep the imports at the top)

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
    
    # SAFE ACCESS: Use getattr to prevent AttributeErrors if fields aren't in the schema
    warnings = getattr(analysis, "warnings", None)
    if warnings:
        lines.extend(["## Ingestion warnings", "", *[f"- {warning}" for warning in warnings], ""])
        
    if any(result.proposal.savings_estimate and not result.proposal.savings_estimate.pricing_available
           for result in analysis.results):
        lines.extend(["Currency pricing is unavailable for one or more proposals; USD savings are not calculated. Relative request changes are reported per workload.", ""])
        
    input_issues = getattr(analysis, "input_issues", None)
    if input_issues:
        lines.extend(["## Input validation", ""])
        lines.extend(
            f"- **{issue.severity.upper()} {issue.code}**"
            f"{f' ({issue.workload_id})' if issue.workload_id else ''}: {issue.message}"
            for issue in input_issues
        )
        lines.append("")

# ... (the rest of the function remains exactly the same)

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

"""Developer 2 — review-only YAML patch: build, apply (in memory), diff and validate.

Never applies anything to a cluster. The patch is a narrow strategic-merge-style fragment that may only set
container `resources.requests.cpu|memory` for the named workload container. validate_patch() proves that by
applying it to the original manifest in memory and diffing every path. Serialised with PyYAML, never concatenated.
deployments.yaml is a normalised snapshot, so the "original" manifest is rendered from it (clearly labelled).
"""


import copy
from typing import Any

import yaml

from app.models.review import PatchArtifact, PatchChange, PatchValidationResult
from app.models.schemas import (
    CheckStatus, CriticCheck, DecisionStatus, OptimizationProposal, RiskLevel, WorkloadResult, WorkloadSpec,
)

# The ONLY shape a patch may have (True = scalar allowed, [x] = list of x).
_ALLOWED: dict = {
    "apiVersion": True, "kind": True, "metadata": {"name": True, "namespace": True},
    "spec": {"template": {"spec": {"containers": [{"name": True, "resources": {"requests": {"cpu": True, "memory": True}}}]}}},
}


def _pct(cur: int | None, new: int | None) -> str:
    return f"{round((new - cur) / cur * 100):+d}%" if cur and new is not None else "n/a"


def render_original_manifest(spec: WorkloadSpec) -> str:
    """Normalised snapshot rendered as a Deployment (NOT the live manifest; no image is invented)."""
    doc = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": spec.name, "namespace": spec.namespace, "labels": {"app": spec.name}},
        "spec": {"replicas": spec.replicas, "selector": {"matchLabels": {"app": spec.name}},
                 "template": {"metadata": {"labels": {"app": spec.name}}, "spec": {"containers": [{
                     "name": spec.name,
                     "resources": {"requests": {"cpu": f"{spec.cpu_request_millicores}m", "memory": f"{spec.memory_request_mib}Mi"},
                                   "limits": {"cpu": f"{spec.cpu_limit_millicores}m", "memory": f"{spec.memory_limit_mib}Mi"}}}]}}},
    }
    return "# Normalised snapshot of deployments.yaml, not the live manifest.\n" + yaml.safe_dump(doc, sort_keys=False)


def spec_from_proposal(p: OptimizationProposal) -> WorkloadSpec | None:
    c = p.current
    vals = (c.cpu_request_millicores, c.cpu_limit_millicores, c.memory_request_mib, c.memory_limit_mib)
    if any(v is None for v in vals):
        return None
    return WorkloadSpec(name=p.workload_id, namespace=p.namespace, cpu_request_millicores=vals[0], cpu_limit_millicores=vals[1],
                        memory_request_mib=vals[2], memory_limit_mib=vals[3])


def build_yaml_patch(proposal: OptimizationProposal) -> str | None:
    p, cur = proposal.proposed, proposal.current
    if p is None or p.cpu_request_millicores is None or p.memory_request_mib is None:
        return None
    body = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": proposal.workload_id, "namespace": proposal.namespace},
        "spec": {"template": {"spec": {"containers": [{
            "name": proposal.workload_id,
            "resources": {"requests": {"cpu": f"{p.cpu_request_millicores}m", "memory": f"{p.memory_request_mib}Mi"}}}]}}},
    }
    header = [
        "# REVIEW-ONLY proposal — not applied automatically. Requests only; limits unchanged.",
        f"# cpu:    {cur.cpu_request_millicores}m -> {p.cpu_request_millicores}m ({_pct(cur.cpu_request_millicores, p.cpu_request_millicores)})",
        f"# memory: {cur.memory_request_mib}Mi -> {p.memory_request_mib}Mi ({_pct(cur.memory_request_mib, p.memory_request_mib)})",
        f"# Illustrative saving: ${proposal.estimated_monthly_saving_usd:.2f}/month (not a billing figure)",
        f"# Assumes the container is named '{proposal.workload_id}'; verify against the real manifest.",
    ]
    return "\n".join(header) + "\n" + yaml.safe_dump(body, sort_keys=False)


# --------------------------------------------------------------------------- validation
def _shape_errors(node: Any, schema: Any, path: str = "patch") -> list[str]:
    if schema is True:
        return [] if not isinstance(node, (dict, list)) else [f"{path}: expected a scalar"]
    if isinstance(schema, list):
        if not isinstance(node, list):
            return [f"{path}: expected a list"]
        return [e for i, item in enumerate(node) for e in _shape_errors(item, schema[0], f"{path}[{i}]")]
    if not isinstance(node, dict):
        return [f"{path}: expected a mapping"]
    errs = [f"{path}.{k}: not allowed in a request-only patch" for k in node if k not in schema]
    return errs + [e for k, v in node.items() if k in schema for e in _shape_errors(v, schema[k], f"{path}.{k}")]


def _flatten(node: Any, path: str = "") -> dict[str, Any]:
    if isinstance(node, dict) and node:
        return {k2: v2 for k, v in node.items() for k2, v2 in _flatten(v, f"{path}.{k}" if path else str(k)).items()}
    if isinstance(node, list) and node:
        out: dict[str, Any] = {}
        for i, v in enumerate(node):
            label = f"[name={v['name']}]" if isinstance(v, dict) and "name" in v else f"[{i}]"
            out.update(_flatten(v, f"{path}{label}"))
        return out
    return {path: node}


def _containers(doc: dict) -> list[dict]:
    return doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])


def _parse(text: str, label: str, errors: list[str]) -> dict | None:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        errors.append(f"{label} is not valid YAML: {str(exc).splitlines()[0]}")
        return None
    if not isinstance(doc, dict):
        errors.append(f"{label} must be a YAML mapping")
        return None
    return doc


def validate_patch(original_yaml: str, patch_yaml: str, recommendation: OptimizationProposal) -> PatchValidationResult:
    """Parse both, apply in memory, and verify ONLY the intended request fields changed."""
    errors: list[str] = []
    original, patch = _parse(original_yaml, "original", errors), _parse(patch_yaml, "patch", errors)
    if original is None or patch is None:
        return PatchValidationResult(valid=False, errors=errors)
    errors += _shape_errors(patch, _ALLOWED)
    for key in ("apiVersion", "kind"):
        if patch.get(key) != original.get(key):
            errors.append(f"patch {key} {patch.get(key)!r} does not match original {original.get(key)!r}")
    for key in ("name", "namespace"):
        if patch.get("metadata", {}).get(key) != original.get("metadata", {}).get(key):
            errors.append(f"patch metadata.{key} does not match the original workload")
    name = recommendation.workload_id
    merged = copy.deepcopy(original)
    targets = [c for c in _containers(merged) if isinstance(c, dict) and c.get("name") == name]
    if len(targets) != 1:
        errors.append(f"expected exactly one container named {name!r} in the original, found {len(targets)}")
    if errors:
        return PatchValidationResult(valid=False, errors=errors)
    for pc in _containers(patch):
        if pc.get("name") != name:
            errors.append(f"patch touches container {pc.get('name')!r}; only {name!r} is allowed")
            continue
        targets[0].setdefault("resources", {}).setdefault("requests", {}).update(pc.get("resources", {}).get("requests", {}))
    if errors:
        return PatchValidationResult(valid=False, errors=errors)

    before, after = _flatten(original), _flatten(merged)
    base = f"spec.template.spec.containers[name={name}].resources.requests"
    allowed = {f"{base}.cpu", f"{base}.memory"}
    changes = [PatchChange(path=p, before=before.get(p), after=after.get(p)) for p in sorted(set(before) | set(after))
               if before.get(p) != after.get(p)]
    errors += [f"unexpected change at {c.path}" for c in changes if c.path not in allowed]
    prop = recommendation.proposed
    if prop is None:
        errors.append("recommendation has no proposed requests")
    else:
        for path, want in ((f"{base}.cpu", f"{prop.cpu_request_millicores}m"), (f"{base}.memory", f"{prop.memory_request_mib}Mi")):
            if after.get(path) != want:
                errors.append(f"{path} is {after.get(path)!r} after the patch but the recommendation says {want!r}")
    return PatchValidationResult(valid=not errors, changes=changes, errors=errors)


def build_review_patch(original_yaml: str, recommendation: OptimizationProposal, decision: WorkloadResult) -> PatchArtifact | None:
    """Only for APPROVED decisions. Deferred / rejected / needs_review / no_change never get a patch."""
    if decision.decision is not DecisionStatus.APPROVED:
        return None
    patch = build_yaml_patch(recommendation)
    if patch is None:
        return None
    validation = validate_patch(original_yaml, patch, recommendation)
    return PatchArtifact(workload_id=recommendation.workload_id, yaml=patch, original_yaml=original_yaml,
                         validation=validation, ready_for_review=validation.valid)


def with_patch(result: WorkloadResult, spec: WorkloadSpec | None = None) -> WorkloadResult:
    """Attach a validated patch to approved results. A patch that fails validation downgrades to needs_review (fail safe)."""
    if result.decision is not DecisionStatus.APPROVED:
        return result
    spec = spec or spec_from_proposal(result.proposal)
    artifact = build_review_patch(render_original_manifest(spec), result.proposal, result) if spec else None
    if artifact and artifact.ready_for_review:
        return result.model_copy(update={"yaml_patch": artifact.yaml})
    why = "; ".join(artifact.validation.errors) if artifact else "original manifest unavailable to validate against"
    check = CriticCheck(name="patch_validation", code="PATCH_INVALID", status=CheckStatus.TRIGGERED,
                        message=f"Patch could not be validated: {why}", evidence={"severity": "review"})
    return result.model_copy(update={"decision": DecisionStatus.NEEDS_REVIEW, "risk_level": RiskLevel.MEDIUM,
                                     "monthly_savings_estimate_usd": 0.0, "yaml_patch": None, "checks": [*result.checks, check],
                                     "proposal": result.proposal.model_copy(update={"priority_score": 0.0}),
                                     "reason": f"Needs review: patch could not be validated ({why})."})

