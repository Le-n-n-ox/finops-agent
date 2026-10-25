from datetime import datetime, timedelta, timezone

from app.models.schemas import AnomalyConfig, UsageRow
from app.services.usage_service import detect_usage_anomalies, percentile, summarize_usage


START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def rows(values):
    return [UsageRow(timestamp=START + timedelta(hours=i), service="svc",
                     cpu_millicores=cpu, memory_mib=memory)
            for i, (cpu, memory) in enumerate(values)]


def test_percentile_uses_documented_linear_interpolation():
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([0, 10], 95) == 9.5


def test_small_sample_summary_omits_unreliable_p99_and_keeps_window():
    summary = summarize_usage(rows([(100, 200), (200, 400), (300, 600)]), p99_min_samples=100)
    assert summary.cpu_p50_m == 200
    assert summary.cpu_p99_m is None and not summary.p99_reliable
    assert summary.sample_count == 3
    assert summary.window_start == START
    assert summary.window_end == START + timedelta(hours=2)


def test_rising_window_produces_deterministic_anomaly_and_trend_hint():
    usage = rows([(100, 200)] * 12 + [(300, 600)] * 6)
    summary = summarize_usage(usage)
    config = AnomalyConfig(recent_window_samples=3, rise_ratio=1.5,
                           min_absolute_increase_cpu_m=100, min_absolute_increase_memory_mib=100)
    first = detect_usage_anomalies(summary, usage, config)
    assert first == detect_usage_anomalies(summary, usage, config)
    assert {item.metric_name for item in first} == {"cpu_millicores", "memory_mib"}
    assert all(item.explanation and item.timestamp == usage[-1].timestamp for item in first)
    assert any("trends upward" in hint for hint in summary.trend_hints)
