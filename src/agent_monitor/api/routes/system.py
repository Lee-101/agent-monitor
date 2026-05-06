"""System and GPU API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ...collectors.registry import CollectorRegistry
from ...storage.sqlite_store import SQLiteStore

router = APIRouter(prefix="/api", tags=["system"])


def create_system_router(registry: CollectorRegistry, store: SQLiteStore) -> APIRouter:
    """Create system routes with injected dependencies."""

    @router.get("/system/current")
    async def get_system_current():
        result = registry.latest_results.get("system")
        if not result:
            return {"status": "no_data", "metrics": []}
        return {
            "status": result.status,
            "collected_at": result.collected_at,
            "metrics": [
                {"name": m.name, "value": m.value, "unit": m.unit, "tags": m.tags}
                for m in result.metrics
            ],
        }

    @router.get("/system/history")
    async def get_system_history(hours: int = Query(default=1, ge=1, le=168)):
        minutes = hours * 60
        metrics = store.get_latest_metrics("system", minutes)
        return {"hours": hours, "count": len(metrics), "metrics": metrics}

    @router.get("/gpu/current")
    async def get_gpu_current():
        result = registry.latest_results.get("gpu")
        if not result:
            return {"status": "no_data", "metrics": []}
        return {
            "status": result.status,
            "collected_at": result.collected_at,
            "metrics": [
                {"name": m.name, "value": m.value, "unit": m.unit, "tags": m.tags}
                for m in result.metrics
            ],
        }

    @router.get("/gpu/history")
    async def get_gpu_history(hours: int = Query(default=1, ge=1, le=168)):
        minutes = hours * 60
        metrics = store.get_latest_metrics("gpu", minutes)
        return {"hours": hours, "count": len(metrics), "metrics": metrics}

    @router.get("/health")
    async def health():
        return {
            "status": "healthy",
            "collectors": registry.collector_names,
            "latest_results": {
                name: {"status": r.status, "collected_at": r.collected_at}
                for name, r in registry.latest_results.items()
            },
        }

    return router
