"""Historical data API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ...collectors.registry import CollectorRegistry
from ...storage.sqlite_store import SQLiteStore

router = APIRouter(prefix="/api/history", tags=["history"])


def create_history_router(registry: CollectorRegistry, store: SQLiteStore) -> APIRouter:
    """Create history routes with injected dependencies."""

    @router.get("/metrics")
    async def get_metric_history(
        collector: str = Query(..., description="Collector name"),
        name: str | None = Query(None, description="Metric name filter"),
        hours: int = Query(default=24, ge=1, le=168),
    ):
        minutes = hours * 60
        metrics = store.get_latest_metrics(collector, minutes)
        if name:
            metrics = [m for m in metrics if m["name"] == name]
        return {
            "collector": collector,
            "metric_name": name,
            "hours": hours,
            "count": len(metrics),
            "metrics": metrics,
        }

    @router.get("/agents")
    async def get_agent_history(
        agent_name: str | None = Query(None),
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        snapshots = store.get_latest_snapshots(agent_name, limit)
        return {"count": len(snapshots), "snapshots": snapshots}

    return router
