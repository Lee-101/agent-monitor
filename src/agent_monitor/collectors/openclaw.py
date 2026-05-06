"""Open Claw collector - stub implementation."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .base import BaseCollector, CollectorResult, MetricPoint

logger = logging.getLogger(__name__)

# Common installation paths to check
SEARCH_PATHS = [
    Path.home() / ".openclaw",
    Path.home() / ".config" / "openclaw",
    Path(os.environ.get("OPENCLAW_HOME", "")) if os.environ.get("OPENCLAW_HOME") else None,
    Path("C:/Users") / os.environ.get("USERNAME", "") / ".openclaw",
]
SEARCH_PATHS = [p for p in SEARCH_PATHS if p is not None]


class OpenClawCollector(BaseCollector):
    """Collects metrics from Open Claw (stub - graceful when not installed)."""

    @property
    def name(self) -> str:
        return "openclaw"

    def is_available(self) -> bool:
        """Check if Open Claw is installed."""
        for path in SEARCH_PATHS:
            if path.exists():
                return True
        return False

    def _find_home(self) -> Path | None:
        """Find Open Claw home directory."""
        for path in SEARCH_PATHS:
            if path.exists():
                return path
        return None

    async def collect(self) -> CollectorResult:
        """Collect Open Claw metrics. Currently a stub."""
        metrics: list[MetricPoint] = []

        home = self._find_home()
        if home is None:
            return CollectorResult(
                collector_name=self.name, metrics=[],
                status="ok", error_message="Open Claw not installed",
            )

        # Basic presence check
        metrics.append(MetricPoint("openclaw_installed", 1, "bool"))
        metrics.append(MetricPoint("openclaw_home_exists", 1, "bool"))

        # TODO: Implement actual Open Claw metrics collection when:
        # 1. Open Claw process detection
        # 2. Session/state file parsing
        # 3. Log analysis
        # This requires knowledge of Open Claw's file structure and state format.

        return CollectorResult(collector_name=self.name, metrics=metrics, status="ok")
