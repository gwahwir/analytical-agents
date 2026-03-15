"""Prometheus metrics for the Control Plane.

Instruments the FastAPI app and exposes custom counters/histograms.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

# Custom business-level metrics
tasks_dispatched = Counter(
    "mc_tasks_dispatched_total",
    "Total tasks dispatched to agents",
    ["agent_id"],
)

tasks_completed = Counter(
    "mc_tasks_completed_total",
    "Total tasks completed successfully",
    ["agent_id"],
)

tasks_failed = Counter(
    "mc_tasks_failed_total",
    "Total tasks that failed",
    ["agent_id"],
)

tasks_cancelled = Counter(
    "mc_tasks_cancelled_total",
    "Total tasks cancelled by operator",
    ["agent_id"],
)

task_duration = Histogram(
    "mc_task_duration_seconds",
    "End-to-end task duration in seconds",
    ["agent_id"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)


def instrument_app(app) -> None:
    """Attach Prometheus instrumentation and expose /metrics."""
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics", "/docs", "/openapi.json"],
    ).instrument(app).expose(app, endpoint="/metrics")
