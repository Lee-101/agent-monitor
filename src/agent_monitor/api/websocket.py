"""WebSocket handler for real-time metric streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..collectors.registry import CollectorRegistry

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts metric updates."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._connections: list[WebSocket] = []
        self._registry = registry
        self._broadcast_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.remove(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast_loop(self, interval: float = 2.0) -> None:
        """Continuously broadcast latest metrics to all connected clients."""
        while True:
            if self._connections:
                data = self._serialize_results()
                dead = []
                for ws in self._connections:
                    try:
                        await ws.send_text(data)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    try:
                        self._connections.remove(ws)
                    except ValueError:
                        pass
            await asyncio.sleep(interval)

    def _serialize_results(self) -> str:
        """Serialize latest collector results to JSON."""
        results = self._registry.latest_results
        payload: dict[str, Any] = {}
        for name, result in results.items():
            payload[name] = {
                "status": result.status,
                "error": result.error_message,
                "collected_at": result.collected_at,
                "metrics": [
                    {
                        "name": m.name,
                        "value": m.value,
                        "unit": m.unit,
                        "tags": m.tags,
                        "timestamp": m.timestamp,
                    }
                    for m in result.metrics
                ],
            }
        return json.dumps(payload)

    def start(self, interval: float = 2.0) -> None:
        self._broadcast_task = asyncio.create_task(self.broadcast_loop(interval))

    async def stop(self) -> None:
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
