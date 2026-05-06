"""Abstract base class and data structures for all collectors."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class MetricPoint:
    """A single metric measurement."""
    name: str
    value: float
    unit: str
    tags: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class CollectorResult:
    """Result from a single collector run."""
    collector_name: str
    metrics: list[MetricPoint] = field(default_factory=list)
    status: str = "ok"  # "ok" | "degraded" | "error"
    error_message: str | None = None
    collected_at: float = field(default_factory=time.time)


class BaseCollector(ABC):
    """Abstract base for all data collectors.

    Subclasses must implement:
    - name: unique identifier
    - collect(): execute one collection cycle
    - is_available(): check if target is present
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this collector."""

    @abstractmethod
    async def collect(self) -> CollectorResult:
        """Execute one collection cycle and return metrics."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this collector's target is present/installed."""

    async def safe_collect(self) -> CollectorResult:
        """Wrapper that catches exceptions and returns error result."""
        try:
            return await self.collect()
        except Exception as e:
            return CollectorResult(
                collector_name=self.name,
                metrics=[],
                status="error",
                error_message=str(e),
            )
