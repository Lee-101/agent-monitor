"""Data retention policy - periodic cleanup of old data."""

from __future__ import annotations

import asyncio
import logging
import time

from .sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class RetentionManager:
    """Manages data retention - periodic cleanup and aggregation."""

    def __init__(self, store: SQLiteStore, retention_days: int = 90) -> None:
        self._store = store
        self._retention_days = retention_days
        self._task: asyncio.Task | None = None

    async def run_loop(self, interval_hours: float = 1.0) -> None:
        """Run retention cleanup periodically."""
        while True:
            try:
                # Aggregate old metrics
                self._store.aggregate_hourly()
                # Cleanup old data
                self._store.cleanup_old_data(self._retention_days)
                logger.info("Retention cleanup completed")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Retention cleanup error")
            await asyncio.sleep(interval_hours * 3600)

    def start(self, interval_hours: float = 1.0) -> None:
        self._task = asyncio.create_task(self.run_loop(interval_hours))
        logger.info("Retention manager started (interval=%.1fh)", interval_hours)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
