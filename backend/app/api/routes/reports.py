"""Decision history, reports, reviewer actions."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import Services, api_errors, get_services
from app.models.review import (
    AuditRecord, DecisionDetail, DecisionRecord, ExpiryResult, ReportDetail, ReviewAction, ReviewRequest,
)
from app.models.schemas import DecisionStatus, InputBundle
from app.services.fingerprints import fingerprint, is_recommendation_stale
from app.services.report_service import build_review_patch, render_original_manifest, spec_from_proposal

router = APIRouter(prefix="/api", tags=["reports"])


def _expiry(record: DecisionRecord, bundle: InputBundle | None) -> ExpiryResult | None:
    if bundle is None:
        return None
    fp = fingerprint(record.workload_id, bundle)
    return is_recommendation_stale(record, fp.metrics_at, fp.config_hash, fp.event_version)


def _try_bundle(svc: Services) -> InputBundle | None:
    try:
        return svc.bundle()
    except Exception:  # noqa: BLE001 - expiry is best-effort; the report itself must still load
        return None


def _detail(svc: Services, record: DecisionRecord, bundle: InputBundle | None) -> DecisionDetail:
    snap = record.snapshot
    patch = None
    if snap is not None and record.decision is DecisionStatus.APPROVED:
        spec = next((s for s in bundle.services if s.name == record.workload_id), None) if bundle else None
        spec = spec or spec_from_proposal(snap.proposal)
        patch = build_review_patch(render_original_manifest(spec), snap.proposal, snap) if spec else None
    return DecisionDetail(record=record, patch=patch, expiry=_expiry(record, bundle),
                          audit=svc.store.audit(decision_id=record.decision_id))


@router.get("/decisions", response_model=list[DecisionRecord])
def decisions(workload_id: str | None = None, status: DecisionStatus | None = None, reviewer_action: ReviewAction | None = None,
              since: datetime | None = None, until: datetime | None = None, q: str | None = Query(None, max_length=100),
              report_id: str | None = None, limit: int = Query(100, ge=1, le=500),
              svc: Services = Depends(get_services)) -> list[DecisionRecord]:
    """Recent critic decisions (also powers the Reports page: search + filters)."""
    with api_errors():
        return svc.store.decisions(workload_id=workload_id, status=status, reviewer_action=reviewer_action, since=since,
                                   until=until, search=q, report_id=report_id, limit=limit)


@router.get("/reports/{report_id}", response_model=ReportDetail)
def report(report_id: str, svc: Services = Depends(get_services)) -> ReportDetail:
    with api_errors():
        rep = svc.store.get_report(report_id)
        if rep is None:
            raise HTTPException(404, f"Unknown report: {report_id}")
        bundle = _try_bundle(svc)
        records = [svc.store.get_decision(f"DEC-{report_id}-{r.workload_id}") for r in rep.results]
        return ReportDetail(report=rep, decisions=[_detail(svc, r, bundle) for r in records if r])


@router.post("/reports/{report_id}/review", response_model=AuditRecord, status_code=201)
def review(report_id: str, req: ReviewRequest, svc: Services = Depends(get_services)) -> AuditRecord:
    """Internal workflow record only. 'Accepted' never deploys anything."""
    with api_errors():
        did = f"DEC-{report_id}-{req.workload_id}"
        record = svc.store.get_decision(did, with_snapshot=False)
        if record is None:
            raise HTTPException(404, f"No decision for {req.workload_id} in report {report_id}")
        if req.action is ReviewAction.ACCEPTED_FOR_IMPLEMENTATION:
            expiry = _expiry(record, _try_bundle(svc))
            if expiry and expiry.stale:
                raise HTTPException(409, f"{expiry.message}: " + "; ".join(expiry.reasons))
        return svc.store.record_reviewer_action(did, req.action, req.comment, req.reviewer, req.outcome,
                                                req.rejection_reasons, req.resource, req.reviewer_guidance)
