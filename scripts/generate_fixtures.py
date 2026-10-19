"""Deterministically (re)generate data/*. Run from repo root: python scripts/generate_fixtures.py

Demo clock: 2026-10-13T09:00+03:00 (policy.yaml: simulation_now). Usage covers the 72h before it.
Scenarios:  A payment-api        -> normal, over-provisioned          -> approved
            B checkout-service   -> over-provisioned + campaign in 23h -> deferred
            C email-worker       -> only 10 samples                    -> insufficient_data / needs_review
            D session-store      -> peaks near request                 -> no_action / no_change
            E recommendation-api -> over-provisioned + incident match  -> deferred (incident)
"""
import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
TZ = timezone(timedelta(hours=3))
END = datetime(2026, 10, 13, 8, 0, tzinfo=TZ)  # last observation (hourly)
random.seed(42)

# name, namespace, replicas, cpu_req, cpu_lim, mem_req, mem_lim, cpu_base, cpu_amp, mem_base, mem_amp, hours
SERVICES = [
    ("payment-api", "payments", 3, 1000, 2000, 4096, 6144, 300, 120, 1400, 200, 72),
    ("checkout-service", "commerce", 3, 1000, 2000, 4096, 6144, 380, 150, 1700, 300, 72),
    ("email-worker", "jobs", 2, 500, 1500, 2048, 3072, 110, 30, 600, 60, 10),
    ("session-store", "core", 2, 500, 1000, 1024, 2048, 380, 90, 800, 120, 72),
    ("recommendation-api", "ml", 2, 1500, 3000, 8192, 12288, 400, 140, 2400, 400, 72),
]

rows = []
for name, ns, rep, cr, cl, mr, ml, cb, ca, mb, ma, hours in SERVICES:
    for i in range(hours):
        ts = END - timedelta(hours=hours - 1 - i)
        wave = math.sin((ts.hour - 6) / 24 * 2 * math.pi)  # daily cycle
        cpu = cb + ca * wave + random.uniform(-15, 15)
        mem = mb + ma * wave + random.uniform(-25, 25)
        rows.append((ts.isoformat(), name, max(0, round(cpu)), max(0, round(mem))))
rows.sort(key=lambda r: (r[1], r[0]))

with open(DATA / "usage_history.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["timestamp", "service", "cpu_millicores", "memory_mib"])
    w.writerows(rows)

with open(DATA / "deployments.yaml", "w") as f:
    f.write("# Normalized resource snapshot (CPU = millicores, memory = MiB). Not raw K8s manifests.\nservices:\n")
    for name, ns, rep, cr, cl, mr, ml, *_ in SERVICES:
        f.write(f"  - name: {name}\n    namespace: {ns}\n    replicas: {rep}\n"
                f"    cpu_request_millicores: {cr}\n    cpu_limit_millicores: {cl}\n"
                f"    memory_request_mib: {mr}\n    memory_limit_mib: {ml}\n")

events = [{
    "name": "Major marketing campaign",
    "start_at": "2026-10-14T08:00:00+03:00",
    "end_at": "2026-10-14T22:00:00+03:00",
    "services": ["checkout-service"],
    "expected_traffic": "high",
    "risk": "high",
    "notes": "Expected customer traffic spike",
}]
(DATA / "business_events.json").write_text(json.dumps(events, indent=2) + "\n")

with open(DATA / "incident_history.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["incident_id", "service", "occurred_at", "pattern", "summary"])
    w.writerow(["INC-2041", "recommendation-api", "2026-08-21T14:10:00+03:00",
                "memory spike after model refresh",
                "OOMKilled after nightly model refresh when memory request was reduced"])

(DATA / "cost_model.json").write_text(json.dumps({
    "cpu_core_monthly_cost_usd": 25.0,
    "memory_gib_monthly_cost_usd": 4.0,
    "note": "Illustrative demo rates only; not a cloud-provider quote",
}, indent=2) + "\n")

print("fixtures written to", DATA)
