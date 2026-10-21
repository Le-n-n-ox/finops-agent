"""Developer 2 — decision history, reviewer audit trail and saved policy.

SQLite (Python standard library). Chosen over JSONL because the Reports page must filter by workload, status,
date and reviewer action. Decision snapshots and reviewer events are APPEND-ONLY: triggers abort any UPDATE/DELETE
so a record can never be edited in place; a review is a new row. Reviewer actions never deploy anything.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from app.models.review import AuditRecord, DecisionRecord, ReviewAction
from app.models.schemas import AnalysisResponse, CriticPolicy, DecisionStatus, WorkloadResult
from app.services.fingerprints import Fingerprint

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports(report_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, policy_version TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(
  decision_id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES reports(report_id), workload_id TEXT NOT NULL, namespace TEXT NOT NULL,
  decision TEXT NOT NULL, risk_level TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, policy_version TEXT NOT NULL,
  config_hash TEXT NOT NULL, metrics_at TEXT, event_version TEXT NOT NULL, payload TEXT NOT NULL,
  rule_version TEXT NOT NULL DEFAULT 'rules-1', input_fingerprint TEXT);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL REFERENCES decisions(decision_id), report_id TEXT NOT NULL,
  workload_id TEXT NOT NULL, action TEXT NOT NULL, comment TEXT, reviewer TEXT, created_at TEXT NOT NULL, outcome TEXT);
CREATE TABLE IF NOT EXISTS policies(id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_dec_workload ON decisions(workload_id, created_at);
CREATE INDEX IF NOT EXISTS idx_rev_decision ON reviews(decision_id);
"""
_APPEND_ONLY = "".join(
    f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;\n"
    for t in ("reports", "decisions", "reviews", "policies") for op in ("UPDATE", "DELETE"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path: str | Path = "finops_history.sqlite3") -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(_SCHEMA + _APPEND_ONLY)
            review_columns = {row[1] for row in self._db.execute("PRAGMA table_info(reviews)")}
            if "outcome" not in review_columns:
                self._db.execute("ALTER TABLE reviews ADD COLUMN outcome TEXT")
            decision_columns = {row[1] for row in self._db.execute("PRAGMA table_info(decisions)")}
            if "rule_version" not in decision_columns:
                self._db.execute("ALTER TABLE decisions ADD COLUMN rule_version TEXT NOT NULL DEFAULT 'rules-1'")
            if "input_fingerprint" not in decision_columns:
                self._db.execute("ALTER TABLE decisions ADD COLUMN input_fingerprint TEXT")

    # ------------------------------------------------------------------ reports + decisions
    def save_decision_record(self, result: WorkloadResult, report_id: str, fp: Fingerprint, policy_version: str,
                             rule_version: str = "rules-1", input_fingerprint: str | None = None,
                             created_at: datetime | None = None) -> str:
        """Persist an immutable decision snapshot and return its ID."""
        did = f"DEC-{report_id}-{result.workload_id}"
        self._db.execute(
            "INSERT INTO decisions(decision_id,report_id,workload_id,namespace,decision,risk_level,reason,created_at,policy_version,config_hash,metrics_at,event_version,payload,rule_version,input_fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (did, report_id, result.workload_id, result.namespace, result.decision.value, result.risk_level.value, result.reason,
             (created_at or _now()).isoformat(), policy_version, fp.config_hash,
             fp.metrics_at.isoformat() if fp.metrics_at else None, fp.event_version, result.model_dump_json(),
             rule_version, input_fingerprint))
        return did

    def save_report(self, response: AnalysisResponse, fingerprints: Mapping[str, Fingerprint], policy_version: str) -> list[str]:
        created = _now()
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute("INSERT INTO reports VALUES (?,?,?,?)",
                                 (response.analysis_id, created.isoformat(), policy_version, response.model_dump_json()))
                ids = [self.save_decision_record(r, response.analysis_id, fingerprints[r.workload_id], policy_version,
                                                 response.rule_version, response.input_fingerprint, created)
                       for r in response.results]
                self._db.execute("COMMIT")
                return ids
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def get_report(self, report_id: str) -> AnalysisResponse | None:
        row = self._db.execute("SELECT payload FROM reports WHERE report_id=?", (report_id,)).fetchone()
        return AnalysisResponse.model_validate_json(row["payload"]) if row else None

    def latest_report(self) -> AnalysisResponse | None:
        row = self._db.execute("SELECT payload FROM reports ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
        return AnalysisResponse.model_validate_json(row["payload"]) if row else None

    def list_reports(self, limit: int = 20) -> list[AnalysisResponse]:
        rows = self._db.execute("SELECT payload FROM reports ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [AnalysisResponse.model_validate_json(r["payload"]) for r in rows]

    # ------------------------------------------------------------------ decisions (query)
    def _record(self, row: sqlite3.Row, with_snapshot: bool) -> DecisionRecord:
        last = self._db.execute("SELECT action FROM reviews WHERE decision_id=? ORDER BY id DESC LIMIT 1", (row["decision_id"],)).fetchone()
        return DecisionRecord(
            decision_id=row["decision_id"], report_id=row["report_id"], workload_id=row["workload_id"], namespace=row["namespace"],
            decision=DecisionStatus(row["decision"]), risk_level=row["risk_level"], reason=row["reason"],
            created_at=row["created_at"], policy_version=row["policy_version"], rule_version=row["rule_version"],
            input_fingerprint=row["input_fingerprint"], config_hash=row["config_hash"],
            metrics_at=row["metrics_at"], event_version=row["event_version"],
            latest_action=ReviewAction(last["action"]) if last else None,
            snapshot=WorkloadResult.model_validate_json(row["payload"]) if with_snapshot else None)

    def get_decision(self, decision_id: str, with_snapshot: bool = True) -> DecisionRecord | None:
        row = self._db.execute("SELECT * FROM decisions WHERE decision_id=?", (decision_id,)).fetchone()
        return self._record(row, with_snapshot) if row else None

    def decisions(self, *, workload_id: str | None = None, status: DecisionStatus | None = None,
                  reviewer_action: ReviewAction | None = None, since: datetime | None = None, until: datetime | None = None,
                  search: str | None = None, report_id: str | None = None, limit: int = 100) -> list[DecisionRecord]:
        sql, args = ["SELECT * FROM decisions d WHERE 1=1"], []
        if workload_id:
            sql.append("AND d.workload_id=?"); args.append(workload_id)
        if status:
            sql.append("AND d.decision=?"); args.append(status.value)
        if report_id:
            sql.append("AND d.report_id=?"); args.append(report_id)
        if since:
            sql.append("AND d.created_at>=?"); args.append(since.isoformat())
        if until:
            sql.append("AND d.created_at<=?"); args.append(until.isoformat())
        if search:
            sql.append("AND (d.workload_id LIKE ? OR d.namespace LIKE ? OR d.reason LIKE ?)"); args += [f"%{search}%"] * 3
        if reviewer_action:
            sql.append("AND (SELECT action FROM reviews r WHERE r.decision_id=d.decision_id ORDER BY r.id DESC LIMIT 1)=?")
            args.append(reviewer_action.value)
        sql.append("ORDER BY d.created_at DESC, d.rowid DESC LIMIT ?"); args.append(max(1, min(limit, 500)))
        return [self._record(r, False) for r in self._db.execute(" ".join(sql), args).fetchall()]

    # ------------------------------------------------------------------ audit trail
    def record_reviewer_action(self, decision_id: str, action: ReviewAction, comment: str | None = None,
                               reviewer: str | None = None, outcome: str | None = None) -> AuditRecord:
        """Append a review event. Never edits the decision. Only APPROVED decisions can be accepted for implementation."""
        dec = self.get_decision(decision_id, with_snapshot=False)
        if dec is None:
            raise KeyError(decision_id)
        if action is ReviewAction.ACCEPTED_FOR_IMPLEMENTATION and dec.decision is not DecisionStatus.APPROVED:
            raise ValueError(f"Only approved decisions can be accepted for implementation (this one is {dec.decision.value}).")
        created = _now()
        with self._lock:
            cur = self._db.execute("INSERT INTO reviews(decision_id,report_id,workload_id,action,comment,reviewer,created_at,outcome) VALUES (?,?,?,?,?,?,?,?)",
                                   (decision_id, dec.report_id, dec.workload_id, action.value, comment, reviewer, created.isoformat(), outcome))
        return AuditRecord(id=cur.lastrowid, decision_id=decision_id, report_id=dec.report_id, workload_id=dec.workload_id,
                           action=action, comment=comment, reviewer=reviewer, created_at=created, outcome=outcome)

    def audit(self, *, decision_id: str | None = None, report_id: str | None = None, limit: int = 200) -> list[AuditRecord]:
        sql, args = "SELECT * FROM reviews WHERE 1=1", []
        if decision_id:
            sql += " AND decision_id=?"; args.append(decision_id)
        if report_id:
            sql += " AND report_id=?"; args.append(report_id)
        rows = self._db.execute(sql + " ORDER BY id ASC LIMIT ?", [*args, limit]).fetchall()
        return [AuditRecord(**{k: r[k] for k in r.keys()}) for r in rows]

    # ------------------------------------------------------------------ policy
    def save_policy(self, policy: CriticPolicy) -> CriticPolicy:
        """Append a new policy version (append-only; the version is assigned here so every edit is traceable)."""
        with self._lock:
            n = self._db.execute("SELECT COUNT(*) FROM policies").fetchone()[0] + 1
            saved = policy.model_copy(update={"version": f"custom-{n}"})
            self._db.execute("INSERT INTO policies(version,payload,created_at) VALUES (?,?,?)",
                             (saved.version, saved.model_dump_json(), _now().isoformat()))
        return saved

    def get_policy(self) -> CriticPolicy | None:
        row = self._db.execute("SELECT payload FROM policies ORDER BY id DESC LIMIT 1").fetchone()
        return CriticPolicy.model_validate_json(row["payload"]) if row else None
