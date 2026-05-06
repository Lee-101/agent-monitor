"""Codex agent collector - process status, state DB, logs."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

import psutil

from .base import BaseCollector, CollectorResult, MetricPoint

logger = logging.getLogger(__name__)


def _get_codex_home() -> Path:
    """Get Codex home directory from env or default."""
    home = os.environ.get("CODEX_HOME")
    if home:
        return Path(home)
    return Path.home() / ".codex"


class CodexCollector(BaseCollector):
    """Collects metrics from Codex agent."""

    def __init__(self) -> None:
        self._codex_home = _get_codex_home()
        self._log_last_ts: int = 0

    @property
    def name(self) -> str:
        return "codex"

    def is_available(self) -> bool:
        """Check if Codex is installed."""
        return (
            (self._codex_home / "state_5.sqlite").exists()
            or (self._codex_home / "config.toml").exists()
            or self._find_codex_processes()
        )

    def _find_codex_processes(self) -> list[psutil.Process]:
        """Find all running Codex processes."""
        found = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc_name = (proc.info.get("name") or "").lower()
                if proc_name in ("codex.exe", "codex"):
                    found.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found

    async def collect(self) -> CollectorResult:
        metrics: list[MetricPoint] = []
        now = time.time()

        # 1. Process status
        procs = self._find_codex_processes()
        metrics.append(MetricPoint("codex_running", int(len(procs) > 0), "bool"))
        metrics.append(MetricPoint("codex_process_count", len(procs), "count"))

        total_cpu = 0.0
        total_mem = 0
        for proc in procs:
            try:
                info = proc.as_dict(attrs=[
                    "pid", "cpu_percent", "memory_info", "memory_percent",
                    "num_threads", "create_time",
                ])
                pid = info["pid"]
                tag = {"pid": str(pid)}

                cpu = info.get("cpu_percent", 0) or 0
                total_cpu += cpu
                metrics.append(MetricPoint("codex_process_cpu", cpu, "%", tag))

                mem_info = info.get("memory_info")
                if mem_info:
                    total_mem += mem_info.rss
                    metrics.append(MetricPoint("codex_process_memory", mem_info.rss, "bytes", tag))

                metrics.append(MetricPoint("codex_process_threads", info.get("num_threads", 0), "count", tag))

                create_time = info.get("create_time", 0)
                if create_time:
                    metrics.append(MetricPoint("codex_process_uptime", now - create_time, "seconds", tag))

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if procs:
            metrics.append(MetricPoint("codex_total_cpu", total_cpu, "%"))
            metrics.append(MetricPoint("codex_total_memory", total_mem, "bytes"))

        # 2. State database
        state_db = self._codex_home / "state_5.sqlite"
        if state_db.exists():
            try:
                self._collect_state_metrics(state_db, metrics)
            except Exception as e:
                logger.warning("Failed to read Codex state DB: %s", e)

        # 3. Logs database
        logs_db = self._codex_home / "logs_2.sqlite"
        if logs_db.exists():
            try:
                self._collect_log_metrics(logs_db, metrics)
            except Exception as e:
                logger.debug("Failed to read Codex logs DB: %s", e)

        # 4. Config
        config_path = self._codex_home / "config.toml"
        if config_path.exists():
            try:
                self._collect_config_metrics(config_path, metrics)
            except Exception as e:
                logger.debug("Failed to read Codex config: %s", e)

        return CollectorResult(collector_name=self.name, metrics=metrics, status="ok")

    def _collect_state_metrics(self, db_path: Path, metrics: list[MetricPoint]) -> None:
        """Collect metrics from Codex state database."""
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            # Total threads
            cur = conn.execute("SELECT COUNT(*) FROM threads")
            total_threads = cur.fetchone()[0]
            metrics.append(MetricPoint("codex_total_threads", total_threads, "count"))

            # Active threads (not archived, updated in last hour)
            cutoff_ms = int((time.time() - 3600) * 1000)
            cur = conn.execute(
                "SELECT COUNT(*) FROM threads WHERE archived = 0 AND updated_at_ms > ?",
                (cutoff_ms,),
            )
            active_threads = cur.fetchone()[0]
            metrics.append(MetricPoint("codex_active_threads", active_threads, "count"))

            # Archived threads
            cur = conn.execute("SELECT COUNT(*) FROM threads WHERE archived = 1")
            archived = cur.fetchone()[0]
            metrics.append(MetricPoint("codex_archived_threads", archived, "count"))

            # Total tokens used across all threads
            cur = conn.execute("SELECT COALESCE(SUM(tokens_used), 0) FROM threads")
            total_tokens = cur.fetchone()[0]
            metrics.append(MetricPoint("codex_total_tokens", total_tokens, "tokens"))

            # Recent thread details
            cur = conn.execute(
                """SELECT id, title, model, tokens_used, cwd, approval_mode, created_at_ms, updated_at_ms
                FROM threads WHERE archived = 0 ORDER BY updated_at_ms DESC LIMIT 1"""
            )
            row = cur.fetchone()
            if row:
                thread_id, title, model, tokens, cwd, approval_mode, created_ms, updated_ms = row
                if model:
                    metrics.append(MetricPoint("codex_current_model", 1, "bool", {"model": model}))
                if tokens:
                    metrics.append(MetricPoint("codex_current_thread_tokens", tokens, "tokens"))
                if approval_mode:
                    metrics.append(MetricPoint("codex_approval_mode", 1, "bool", {"mode": approval_mode}))

            # Thread goals
            cur = conn.execute(
                """SELECT COUNT(*), COALESCE(SUM(token_budget), 0), COALESCE(SUM(tokens_used), 0)
                FROM thread_goals WHERE status = 'active'"""
            )
            row = cur.fetchone()
            if row:
                metrics.append(MetricPoint("codex_active_goals", row[0], "count"))
                metrics.append(MetricPoint("codex_goal_token_budget", row[1], "tokens"))
                metrics.append(MetricPoint("codex_goal_tokens_used", row[2], "tokens"))

            # Agent jobs
            cur = conn.execute(
                "SELECT status, COUNT(*) FROM agent_jobs GROUP BY status"
            )
            for row in cur.fetchall():
                status, count = row
                metrics.append(MetricPoint("codex_agent_jobs", count, "count", {"status": status}))

            # Thread spawn edges (sub-agent activity)
            cur = conn.execute("SELECT COUNT(*) FROM thread_spawn_edges")
            spawn_count = cur.fetchone()[0]
            metrics.append(MetricPoint("codex_subagent_spawns", spawn_count, "count"))

        finally:
            conn.close()

    def _collect_log_metrics(self, db_path: Path, metrics: list[MetricPoint]) -> None:
        """Collect metrics from Codex logs database."""
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            # Log level counts
            cur = conn.execute("SELECT level, COUNT(*) FROM logs GROUP BY level")
            for row in cur.fetchall():
                level, count = row
                metrics.append(MetricPoint("codex_log_count", count, "count", {"level": level}))

            # Recent error/warning count (last 10 minutes)
            cutoff_ns = int((time.time() - 600) * 1_000_000_000)
            cur = conn.execute(
                "SELECT COUNT(*) FROM logs WHERE level IN ('ERROR', 'WARN') AND ts > ?",
                (cutoff_ns // 1_000_000_000,),
            )
            recent_errors = cur.fetchone()[0]
            metrics.append(MetricPoint("codex_recent_errors", recent_errors, "count"))

            # Error rate (errors per minute in last hour)
            cutoff_hour = int((time.time() - 3600))
            cur = conn.execute(
                "SELECT COUNT(*) FROM logs WHERE level = 'ERROR' AND ts > ?",
                (cutoff_hour,),
            )
            hour_errors = cur.fetchone()[0]
            metrics.append(MetricPoint("codex_hour_errors", hour_errors, "count"))
            metrics.append(MetricPoint("codex_error_rate", hour_errors / 60.0, "/min"))

            # Unique targets (modules) with errors
            cur = conn.execute(
                "SELECT DISTINCT target FROM logs WHERE level = 'ERROR' AND ts > ? LIMIT 10",
                (cutoff_hour,),
            )
            error_targets = [r[0] for r in cur.fetchall()]
            metrics.append(MetricPoint("codex_error_modules", len(error_targets), "count"))

        finally:
            conn.close()

    def _collect_config_metrics(self, config_path: Path, metrics: list[MetricPoint]) -> None:
        """Collect metrics from Codex config file."""
        try:
            content = config_path.read_text(encoding="utf-8")

            # Extract model
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("model") and "=" in line:
                    model = line.split("=", 1)[1].strip().strip('"').strip("'")
                    metrics.append(MetricPoint("codex_config_model", 1, "bool", {"model": model}))
                    break

            # Extract base_url
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("base_url") and "=" in line:
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    metrics.append(MetricPoint("codex_config_base_url", 1, "bool", {"url": url}))
                    break

            # Count enabled plugins
            plugin_count = content.count("enabled = true")
            metrics.append(MetricPoint("codex_enabled_plugins", plugin_count, "count"))

        except OSError:
            pass
