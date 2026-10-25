"""Deterministic usage summaries and configurable baseline anomaly checks."""
from __future__ import annotations

from statistics import fmean

from app.models.schemas import AnomalyConfig, UsageAnomaly, UsageRow, UsageSummary


def percentile(values: list[float], percentile_value: float) -> float:
    """Linear interpolation over sorted observations at position (n - 1) * p."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize_usage(
    metrics: list[UsageRow], workload_id: str | None = None, p99_min_samples: int = 100,
) -> UsageSummary:
    """Return distribution and exact window; omit P99 until the sample threshold is met."""
    ordered = sorted(metrics, key=lambda metric: metric.timestamp)
    workload = workload_id or (ordered[0].service if ordered else "unknown")
    if not ordered:
        return UsageSummary(workload_id=workload)

    cpu = [float(row.cpu_millicores) for row in ordered]
    memory = [float(row.memory_mib) for row in ordered]
    p99_reliable = len(ordered) >= p99_min_samples
    hints: list[str] = []
    split = max(1, len(ordered) // 4)
    for name, values in (("CPU", cpu), ("memory", memory)):
        early, recent = fmean(values[:split]), fmean(values[-split:])
        if early > 0 and recent >= early * 1.2:
            hints.append(f"{name} usage trends upward in the most recent quarter of the window.")
        elif early > 0 and recent <= early * 0.8:
            hints.append(f"{name} usage trends downward in the most recent quarter of the window.")

    return UsageSummary(
        workload_id=workload,
        cpu_p50_m=round(percentile(cpu, 50), 2),
        cpu_p95_m=round(percentile(cpu, 95), 2),
        cpu_p99_m=round(percentile(cpu, 99), 2) if p99_reliable else None,
        cpu_peak_m=max(cpu),
        memory_p50_mib=round(percentile(memory, 50), 2),
        memory_p95_mib=round(percentile(memory, 95), 2),
        memory_p99_mib=round(percentile(memory, 99), 2) if p99_reliable else None,
        memory_peak_mib=max(memory),
        sample_count=len(ordered),
        window_start=ordered[0].timestamp,
        window_end=ordered[-1].timestamp,
        p99_reliable=p99_reliable,
        trend_hints=hints,
    )


def detect_usage_anomalies(
    summary: UsageSummary,
    recent_metrics: list[UsageRow],
    config: AnomalyConfig | None = None,
) -> list[UsageAnomaly]:
    """Compare a recent window's mean with the preceding baseline mean."""
    config = config or AnomalyConfig()
    ordered = sorted(recent_metrics, key=lambda metric: metric.timestamp)
    window = max(1, config.recent_window_samples)
    if len(ordered) <= window or summary.sample_count != len(ordered):
        return []

    baseline_rows, recent_rows = ordered[:-window], ordered[-window:]
    found: list[UsageAnomaly] = []
    for name, field, min_increase in (
        ("cpu_millicores", "cpu_millicores", config.min_absolute_increase_cpu_m),
        ("memory_mib", "memory_mib", config.min_absolute_increase_memory_mib),
    ):
        baseline_values = [float(getattr(row, field)) for row in baseline_rows]
        recent_values = [float(getattr(row, field)) for row in recent_rows]
        baseline = fmean(baseline_values)
        observed = fmean(recent_values)
        increase = observed - baseline
        if increase < min_increase or (baseline > 0 and observed < baseline * config.rise_ratio):
            continue
        ratio = observed / baseline if baseline > 0 else float("inf")
        severity = "high" if ratio >= config.rise_ratio * 1.5 else "medium"
        units = "mCPU" if field == "cpu_millicores" else "MiB"
        found.append(UsageAnomaly(
            metric_name=name,
            observed_value=round(observed, 2),
            baseline_value=round(baseline, 2),
            severity=severity,
            timestamp=recent_rows[-1].timestamp,
            explanation=(f"Recent {name} average is {observed:.1f} {units}, "
                         f"up from a baseline of {baseline:.1f} {units} ({increase:.1f} {units} increase)."),
        ))
    return found
