"""Alert evaluation engine."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from ..collectors.base import CollectorResult
from ..collectors.registry import CollectorRegistry
from ..storage.sqlite_store import SQLiteStore
from .rules import AlertRule, evaluate_condition, load_rules, DEFAULT_RULES
from .notifiers import BaseNotifier, create_notifiers

logger = logging.getLogger(__name__)


class AlertEngine:
    """Evaluates alert rules against collector results and triggers notifications."""

    def __init__(
        self,
        registry: CollectorRegistry,
        store: SQLiteStore,
        rules_path: str | Path | None = None,
        notifier_configs: list[dict] | None = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._rules: list[AlertRule] = []
        self._notifiers: list[BaseNotifier] = []
        self._rules_path = rules_path
        self._task: asyncio.Task | None = None
        self._active_alerts: dict[str, float] = {}  # rule_name -> triggered_at

        # Load rules
        if rules_path and Path(rules_path).exists():
            self._rules = load_rules(rules_path)
        if not self._rules:
            self._rules = DEFAULT_RULES.copy()

        # Create notifiers
        self._notifiers = create_notifiers(notifier_configs or [])

        logger.info("Alert engine initialized with %d rules", len(self._rules))

    def _build_metrics_dict(self) -> dict[str, dict[str, float]]:
        """Build a nested dict of collector -> metric_name -> value from latest results."""
        result: dict[str, dict[str, float]] = {}
        for name, collector_result in self._registry.latest_results.items():
            metrics = {}
            for m in collector_result.metrics:
                metrics[m.name] = m.value
            result[name] = metrics
        return result

    def evaluate(self) -> list[AlertRule]:
        """Evaluate all rules and return newly triggered ones."""
        metrics = self._build_metrics_dict()
        now = time.time()
        triggered = []

        for rule in self._rules:
            if not rule.enabled:
                continue

            condition_met = evaluate_condition(rule.condition, metrics)

            if condition_met is None:
                # Metric not found, skip
                continue

            if condition_met:
                # Condition is true
                if rule._last_eval_true == 0:
                    rule._last_eval_true = now

                # Check if duration threshold is met
                elapsed = now - rule._last_eval_true
                if elapsed >= rule.duration_seconds:
                    # Check if we already triggered this alert
                    if rule.name not in self._active_alerts:
                        rule._triggered_at = now
                        self._active_alerts[rule.name] = now
                        triggered.append(rule)
            else:
                # Condition is false, reset
                rule._last_eval_true = 0
                if rule.name in self._active_alerts:
                    del self._active_alerts[rule.name]

        return triggered

    def _fire_alert(self, rule: AlertRule) -> None:
        """Store alert in database and send notifications."""
        # Store in DB
        alert_id = self._store.store_alert(
            rule_name=rule.name,
            severity=rule.severity,
            message=rule.message,
        )

        # Notify
        for notifier in self._notifiers:
            try:
                notifier.notify(
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=rule.message,
                )
            except Exception as e:
                logger.error("Notifier error: %s", e)

        logger.warning("ALERT [%s] %s: %s (id=%d)", rule.severity, rule.name, rule.message, alert_id)

    async def run_loop(self, interval: float = 10.0) -> None:
        """Run the alert evaluation loop."""
        while True:
            try:
                triggered = self.evaluate()
                for rule in triggered:
                    self._fire_alert(rule)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Alert evaluation error")
            await asyncio.sleep(interval)

    def start(self, interval: float = 10.0) -> None:
        self._task = asyncio.create_task(self.run_loop(interval))
        logger.info("Alert engine started (interval=%ss)", interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Alert engine stopped")

    @property
    def active_alerts(self) -> dict[str, float]:
        return self._active_alerts.copy()

    @property
    def rules(self) -> list[AlertRule]:
        return self._rules.copy()
