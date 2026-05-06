"""Alert rule definitions and parsing."""

from __future__ import annotations

import operator
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml


@dataclass
class AlertRule:
    """A single alert rule."""
    name: str
    condition: str  # e.g. "system.cpu_percent_avg > 90"
    severity: str = "warning"  # "info" | "warning" | "critical"
    message: str = ""
    duration_seconds: float = 0  # Must persist for this duration
    enabled: bool = True

    # Internal state
    _triggered_at: float = field(default=0, repr=False)
    _last_eval_true: float = field(default=0, repr=False)


# Simple condition parser: "collector.metric_name op value"
_CONDITION_RE = re.compile(
    r"^(?P<collector>[a-z_]+)\.(?P<metric>[a-z_]+)\s*(?P<op>[><=!]+)\s*(?P<value>[\d.]+)$"
)

_OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def evaluate_condition(
    condition: str,
    metrics_by_collector: dict[str, dict[str, float]],
) -> bool | None:
    """Evaluate a simple condition expression.

    Returns True if condition is met, False if not, None if metric not found.
    """
    match = _CONDITION_RE.match(condition.strip())
    if not match:
        return None

    collector = match.group("collector")
    metric = match.group("metric")
    op_str = match.group("op")
    threshold = float(match.group("value"))

    op_func = _OPS.get(op_str)
    if not op_func:
        return None

    # Get metric value
    collector_metrics = metrics_by_collector.get(collector, {})
    value = collector_metrics.get(metric)
    if value is None:
        return None

    return op_func(value, threshold)


def load_rules(rules_path: str | Path) -> list[AlertRule]:
    """Load alert rules from a YAML file."""
    path = Path(rules_path)
    if not path.exists():
        return []

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    rules = []
    for rule_data in data.get("rules", []):
        if not isinstance(rule_data, dict):
            continue
        rule = AlertRule(
            name=rule_data.get("name", "unnamed"),
            condition=rule_data.get("condition", ""),
            severity=rule_data.get("severity", "warning"),
            message=rule_data.get("message", ""),
            duration_seconds=_parse_duration(rule_data.get("duration", "0s")),
            enabled=rule_data.get("enabled", True),
        )
        if rule.condition:
            rules.append(rule)

    return rules


def _parse_duration(duration_str: str) -> float:
    """Parse a duration string like '5m', '30s', '1h' to seconds."""
    duration_str = duration_str.strip().lower()
    if duration_str == "0" or duration_str == "0s":
        return 0

    match = re.match(r"^(\d+(?:\.\d+)?)\s*(s|m|h|d)?$", duration_str)
    if not match:
        return 0

    value = float(match.group(1))
    unit = match.group(2) or "s"

    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multipliers.get(unit, 1)


# Built-in default rules
DEFAULT_RULES = [
    AlertRule(
        name="high_cpu",
        condition="system.cpu_percent_avg > 90",
        severity="warning",
        message="CPU 使用率超过 90%",
        duration_seconds=300,
    ),
    AlertRule(
        name="high_memory",
        condition="system.memory_percent > 90",
        severity="warning",
        message="内存使用率超过 90%",
        duration_seconds=300,
    ),
    AlertRule(
        name="high_gpu_temp",
        condition="gpu.gpu_temperature > 85",
        severity="critical",
        message="GPU 温度超过 85°C",
        duration_seconds=120,
    ),
    AlertRule(
        name="claude_code_down",
        condition="claude_code.claude_code_running == 0",
        severity="info",
        message="Claude Code 未运行",
        duration_seconds=0,
    ),
    AlertRule(
        name="hermes_down",
        condition="hermes.hermes_running == 0",
        severity="info",
        message="Hermes Agent 未运行",
        duration_seconds=0,
    ),
]
