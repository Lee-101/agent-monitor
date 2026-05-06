"""Hermes Agent collector - process status, SQLite state, logs."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

import psutil

from .base import BaseCollector, CollectorResult, MetricPoint
from .log_analyzer import LogAnalyzer

logger = logging.getLogger(__name__)


def _get_hermes_home() -> Path:
    """Get Hermes home directory from env or default."""
    home = os.environ.get("HERMES_HOME")
    if home:
        return Path(home)
    return Path.home() / ".hermes"


class HermesCollector(BaseCollector):
    """Collects metrics from Hermes Agent."""

    def __init__(self) -> None:
        self._hermes_home = _get_hermes_home()
        self._log_analyzer = LogAnalyzer()

    @property
    def name(self) -> str:
        return "hermes"

    def is_available(self) -> bool:
        """Check if Hermes is installed by looking for state.db or logs."""
        return (
            (self._hermes_home / "state.db").exists()
            or (self._hermes_home / "logs").is_dir()
            or self._find_hermes_process() is not None
        )

    def _find_hermes_process(self) -> psutil.Process | None:
        """Find a running Hermes agent process."""
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if "run_agent.py" in cmdline or ("hermes" in name and "python" in name):
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    async def collect(self) -> CollectorResult:
        metrics: list[MetricPoint] = []
        now = time.time()

        # 1. Process status
        proc = self._find_hermes_process()
        if proc:
            try:
                info = proc.as_dict(attrs=[
                    "pid", "cpu_percent", "memory_info", "memory_percent",
                    "num_threads", "status", "create_time",
                ])
                pid = info["pid"]
                tag = {"pid": str(pid)}

                metrics.append(MetricPoint("hermes_running", 1, "bool"))
                metrics.append(MetricPoint("hermes_cpu_percent", info.get("cpu_percent", 0), "%", tag))

                mem_info = info.get("memory_info")
                if mem_info:
                    metrics.append(MetricPoint("hermes_memory_rss", mem_info.rss, "bytes", tag))

                metrics.append(MetricPoint("hermes_memory_percent", info.get("memory_percent", 0), "%", tag))
                metrics.append(MetricPoint("hermes_threads", info.get("num_threads", 0), "count", tag))

                create_time = info.get("create_time", 0)
                if create_time:
                    metrics.append(MetricPoint("hermes_uptime", now - create_time, "seconds", tag))

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                metrics.append(MetricPoint("hermes_running", 0, "bool"))
        else:
            metrics.append(MetricPoint("hermes_running", 0, "bool"))

        # 2. SQLite state database
        db_path = self._hermes_home / "state.db"
        if db_path.exists():
            try:
                self._collect_db_metrics(db_path, metrics)
            except Exception as e:
                logger.warning("Failed to read Hermes state DB: %s", e)

        # 3. Log analysis
        for log_name in ("agent.log", "errors.log"):
            log_path = self._hermes_home / "logs" / log_name
            if log_path.exists():
                try:
                    analysis = self._log_analyzer.analyze(log_path)
                    prefix = log_name.replace(".log", "")
                    metrics.append(MetricPoint(f"hermes_{prefix}_new_lines", analysis.new_lines, "count"))
                    metrics.append(MetricPoint(f"hermes_{prefix}_errors", analysis.error_count, "count"))
                    metrics.append(MetricPoint(f"hermes_{prefix}_warnings", analysis.warning_count, "count"))
                    metrics.append(MetricPoint(f"hermes_{prefix}_errors_per_min", analysis.errors_per_minute, "/min"))
                except Exception as e:
                    logger.debug("Log analysis failed for %s: %s", log_path, e)

        # 4. Gateway status
        gateway_pid_file = self._hermes_home / "gateway.pid"
        if gateway_pid_file.exists():
            try:
                pid_text = gateway_pid_file.read_text().strip()
                pid = int(pid_text)
                gateway_running = psutil.pid_exists(pid)
                metrics.append(MetricPoint("hermes_gateway_running", int(gateway_running), "bool", {"pid": str(pid)}))
            except (ValueError, OSError):
                pass

        gateway_state_file = self._hermes_home / "gateway_state.json"
        if gateway_state_file.exists():
            try:
                state = json.loads(gateway_state_file.read_text())
                for key, value in state.items():
                    if isinstance(value, (int, float)):
                        metrics.append(MetricPoint(f"hermes_gateway_{key}", value, "", {"source": "gateway_state"}))
            except (json.JSONDecodeError, OSError):
                pass

        return CollectorResult(collector_name=self.name, metrics=metrics, status="ok")

    def _collect_db_metrics(self, db_path: Path, metrics: list[MetricPoint]) -> None:
        """Collect metrics from Hermes SQLite state database."""
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            # Active sessions (not ended)
            cur = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL"
            )
            active = cur.fetchone()[0]
            metrics.append(MetricPoint("hermes_active_sessions", active, "count"))

            # Total sessions
            cur = conn.execute("SELECT COUNT(*) FROM sessions")
            total = cur.fetchone()[0]
            metrics.append(MetricPoint("hermes_total_sessions", total, "count"))

            # Aggregate token usage from recent sessions
            since = time.time() - 3600  # Last hour
            cur = conn.execute(
                """SELECT
                    COALESCE(SUM(input_tokens), 0),
                    COALESCE(SUM(output_tokens), 0),
                    COALESCE(SUM(cache_read_tokens), 0),
                    COALESCE(SUM(message_count), 0),
                    COALESCE(SUM(tool_call_count), 0),
                    COALESCE(SUM(estimated_cost_usd), 0)
                FROM sessions WHERE started_at > ?""",
                (since,),
            )
            row = cur.fetchone()
            if row:
                metrics.append(MetricPoint("hermes_hour_input_tokens", row[0], "tokens"))
                metrics.append(MetricPoint("hermes_hour_output_tokens", row[1], "tokens"))
                metrics.append(MetricPoint("hermes_hour_cache_tokens", row[2], "tokens"))
                metrics.append(MetricPoint("hermes_hour_messages", row[3], "count"))
                metrics.append(MetricPoint("hermes_hour_tool_calls", row[4], "count"))
                metrics.append(MetricPoint("hermes_hour_cost_usd", row[5], "USD"))

            # All-time totals
            cur = conn.execute(
                """SELECT
                    COALESCE(SUM(input_tokens), 0),
                    COALESCE(SUM(output_tokens), 0),
                    COALESCE(SUM(message_count), 0),
                    COALESCE(SUM(estimated_cost_usd), 0)
                FROM sessions"""
            )
            row = cur.fetchone()
            if row:
                metrics.append(MetricPoint("hermes_total_input_tokens", row[0], "tokens"))
                metrics.append(MetricPoint("hermes_total_output_tokens", row[1], "tokens"))
                metrics.append(MetricPoint("hermes_total_messages", row[2], "count"))
                metrics.append(MetricPoint("hermes_total_cost_usd", row[3], "USD"))

        finally:
            conn.close()
