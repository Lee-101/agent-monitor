"""Alert API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...storage.sqlite_store import SQLiteStore

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def create_alerts_router(store: SQLiteStore) -> APIRouter:
    """Create alert routes with injected dependencies."""

    @router.get("")
    async def list_alerts(severity: str | None = None, acknowledged: bool | None = None, limit: int = 50):
        alerts = store.get_alerts(severity=severity, acknowledged=acknowledged, limit=limit)
        return {"count": len(alerts), "alerts": alerts}

    @router.post("/{alert_id}/acknowledge")
    async def acknowledge_alert(alert_id: int):
        success = store.acknowledge_alert(alert_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
        return {"success": True, "alert_id": alert_id}

    return router
