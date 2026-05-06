"""Agent-specific API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...collectors.registry import CollectorRegistry
from ...storage.sqlite_store import SQLiteStore

router = APIRouter(prefix="/api/agents", tags=["agents"])

AGENT_COLLECTORS = ["hermes", "claude_code", "openclaw", "codex"]


def create_agents_router(registry: CollectorRegistry, store: SQLiteStore) -> APIRouter:
    """Create agent routes with injected dependencies."""

    @router.get("")
    async def list_agents():
        agents = []
        for name in AGENT_COLLECTORS:
            result = registry.latest_results.get(name)
            if result:
                metrics_dict = {m.name: m.value for m in result.metrics}
                agents.append({
                    "name": name,
                    "status": result.status,
                    "collected_at": result.collected_at,
                    "running": bool(metrics_dict.get(f"{name}_running", 0)),
                    "cpu_percent": metrics_dict.get(f"{name}_cpu_percent", 0),
                    "memory_rss": metrics_dict.get(f"{name}_memory_rss", 0),
                    "error": result.error_message,
                })
            else:
                agents.append({"name": name, "status": "not_collected", "running": False})
        return {"agents": agents}

    @router.get("/{name}")
    async def get_agent(name: str):
        if name not in AGENT_COLLECTORS:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
        result = registry.latest_results.get(name)
        if not result:
            return {"name": name, "status": "no_data", "metrics": []}
        return {
            "name": name,
            "status": result.status,
            "collected_at": result.collected_at,
            "error": result.error_message,
            "metrics": [
                {"name": m.name, "value": m.value, "unit": m.unit, "tags": m.tags}
                for m in result.metrics
            ],
        }

    @router.get("/{name}/history")
    async def get_agent_history(name: str, limit: int = Query(default=100, ge=1, le=1000)):
        if name not in AGENT_COLLECTORS:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
        snapshots = store.get_latest_snapshots(name, limit)
        return {"name": name, "count": len(snapshots), "snapshots": snapshots}

    @router.get("/{name}/logs")
    async def get_agent_logs(name: str, limit: int = Query(default=100, ge=1, le=500)):
        if name not in AGENT_COLLECTORS:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
        result = registry.latest_results.get(name)
        if not result:
            return {"name": name, "logs": []}

        # Extract log-related metrics
        logs = []
        for m in result.metrics:
            if "error" in m.name or "warning" in m.name:
                logs.append({"name": m.name, "value": m.value, "unit": m.unit, "tags": m.tags})

        return {"name": name, "count": len(logs), "logs": logs[:limit]}

    return router
