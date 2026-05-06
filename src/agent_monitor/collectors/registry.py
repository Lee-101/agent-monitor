"""Collector registry - discovers, registers, and manages all collectors."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from .base import BaseCollector, CollectorResult

logger = logging.getLogger(__name__)


class CollectorRegistry:
    """Central registry that manages collector lifecycle and execution."""

    def __init__(self) -> None:
        self._collectors: dict[str, BaseCollector] = {}
        self._intervals: dict[str, float] = {}
        self._latest_results: dict[str, CollectorResult] = {}
        self._tasks: list[asyncio.Task] = []
        self._callbacks: list[Callable[[str, CollectorResult], None]] = []

    def register(self, collector: BaseCollector, interval_seconds: float = 5.0) -> bool:
        """Register a collector if it is available. Returns True if registered."""
        if not collector.is_available():
            logger.info("Collector '%s' not available, skipping", collector.name)
            return False
        self._collectors[collector.name] = collector
        self._intervals[collector.name] = interval_seconds
        logger.info("Registered collector '%s' (interval=%ss)", collector.name, interval_seconds)
        return True

    def on_result(self, callback: Callable[[str, CollectorResult], None]) -> None:
        """Register a callback invoked after each collection cycle."""
        self._callbacks.append(callback)

    @property
    def latest_results(self) -> dict[str, CollectorResult]:
        """Latest collected results from all collectors."""
        return self._latest_results.copy()

    async def collect_once(self) -> dict[str, CollectorResult]:
        """Run all collectors once and return results."""
        results: dict[str, CollectorResult] = {}
        tasks = {
            name: asyncio.create_task(c.safe_collect())
            for name, c in self._collectors.items()
        }
        for name, task in tasks.items():
            result = await task
            results[name] = result
            self._latest_results[name] = result
            for cb in self._callbacks:
                try:
                    cb(name, result)
                except Exception:
                    logger.exception("Callback error for collector '%s'", name)
        return results

    async def _run_collector_loop(self, name: str, collector: BaseCollector, interval: float) -> None:
        """Run a single collector in a loop."""
        while True:
            try:
                result = await collector.safe_collect()
                self._latest_results[name] = result
                for cb in self._callbacks:
                    try:
                        cb(name, result)
                    except Exception:
                        logger.exception("Callback error for collector '%s'", name)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in collector loop '%s'", name)
            await asyncio.sleep(interval)

    async def start_all(self) -> None:
        """Start all collectors as background tasks."""
        for name, collector in self._collectors.items():
            interval = self._intervals.get(name, 5.0)
            task = asyncio.create_task(
                self._run_collector_loop(name, collector, interval)
            )
            self._tasks.append(task)
            logger.info("Started collector loop '%s'", name)

    async def stop_all(self) -> None:
        """Cancel all collector tasks."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("All collectors stopped")

    @property
    def collector_names(self) -> list[str]:
        return list(self._collectors.keys())
