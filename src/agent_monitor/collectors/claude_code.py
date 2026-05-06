"""Claude Code collector - process status, stats-cache, history, telemetry."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import psutil

from .base import BaseCollector, CollectorResult, MetricPoint
from .log_analyzer import LogAnalyzer

logger = logging.getLogger(__name__)


def _get_claude_home() -> Path:
    """Get Claude Code home directory from env or default."""
    home = os.environ.get("CLAUDE_HOME")
    if home:
        return Path(home)
    return Path.home() / ".claude"


class ClaudeCodeCollector(BaseCollector):
    """Collects metrics from Claude Code."""

    def __init__(self) -> None:
        self._claude_home = _get_claude_home()
        self._log_analyzer = LogAnalyzer()
        self._history_pos: int = 0

    @property
    def name(self) -> str:
        return "claude_code"

    def is_available(self) -> bool:
        """Check if Claude Code is installed."""
        return (
            (self._claude_home / "stats-cache.json").exists()
            or (self._claude_home / "history.jsonl").exists()
            or self._find_claude_process() is not None
        )

    def _find_claude_process(self) -> psutil.Process | None:
        """Find a running Claude Code process."""
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                proc_name = (proc.info.get("name") or "").lower()
                if "claude" in proc_name and proc_name.endswith(".exe"):
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    async def collect(self) -> CollectorResult:
        metrics: list[MetricPoint] = []
        now = time.time()

        # 1. Process status
        procs = self._find_all_claude_processes()
        metrics.append(MetricPoint("claude_code_running", int(len(procs) > 0), "bool"))
        metrics.append(MetricPoint("claude_code_process_count", len(procs), "count"))

        for proc in procs:
            try:
                info = proc.as_dict(attrs=[
                    "pid", "cpu_percent", "memory_info", "memory_percent",
                    "num_threads", "create_time",
                ])
                pid = info["pid"]
                tag = {"pid": str(pid)}

                metrics.append(MetricPoint("claude_code_cpu_percent", info.get("cpu_percent", 0), "%", tag))

                mem_info = info.get("memory_info")
                if mem_info:
                    metrics.append(MetricPoint("claude_code_memory_rss", mem_info.rss, "bytes", tag))

                metrics.append(MetricPoint("claude_code_memory_percent", info.get("memory_percent", 0), "%", tag))
                metrics.append(MetricPoint("claude_code_threads", info.get("num_threads", 0), "count", tag))

                create_time = info.get("create_time", 0)
                if create_time:
                    metrics.append(MetricPoint("claude_code_uptime", now - create_time, "seconds", tag))

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # 2. Stats cache
        stats_path = self._claude_home / "stats-cache.json"
        if stats_path.exists():
            try:
                self._collect_stats_cache(stats_path, metrics)
            except Exception as e:
                logger.warning("Failed to read Claude Code stats-cache: %s", e)

        # 3. History analysis
        history_path = self._claude_home / "history.jsonl"
        if history_path.exists():
            try:
                self._collect_history(history_path, metrics)
            except Exception as e:
                logger.debug("History analysis failed: %s", e)

        # 4. Telemetry errors
        telemetry_dir = self._claude_home / "telemetry"
        if telemetry_dir.is_dir():
            try:
                self._collect_telemetry(telemetry_dir, metrics)
            except Exception as e:
                logger.debug("Telemetry analysis failed: %s", e)

        # 5. Active sessions
        sessions_dir = self._claude_home / "sessions"
        if sessions_dir.is_dir():
            try:
                session_files = list(sessions_dir.glob("*.json"))
                metrics.append(MetricPoint("claude_code_session_files", len(session_files), "count"))
            except Exception:
                pass

        return CollectorResult(collector_name=self.name, metrics=metrics, status="ok")

    def _find_all_claude_processes(self) -> list[psutil.Process]:
        """Find all running Claude Code processes."""
        found = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc_name = (proc.info.get("name") or "").lower()
                if "claude" in proc_name and proc_name.endswith(".exe"):
                    found.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found

    def _collect_stats_cache(self, path: Path, metrics: list[MetricPoint]) -> None:
        """Parse stats-cache.json (v3 format)."""
        data = json.loads(path.read_text(encoding="utf-8"))

        # Aggregate stats
        metrics.append(MetricPoint("claude_code_total_sessions", data.get("totalSessions", 0), "count"))
        metrics.append(MetricPoint("claude_code_total_messages", data.get("totalMessages", 0), "count"))

        # Model usage
        model_usage = data.get("modelUsage", {})
        for model, usage in model_usage.items():
            tag = {"model": model}
            if isinstance(usage, dict):
                metrics.append(MetricPoint("claude_code_input_tokens", usage.get("inputTokens", 0), "tokens", tag))
                metrics.append(MetricPoint("claude_code_output_tokens", usage.get("outputTokens", 0), "tokens", tag))
                metrics.append(MetricPoint("claude_code_cache_read_tokens", usage.get("cacheReadInputTokens", 0), "tokens", tag))
                metrics.append(MetricPoint("claude_code_cache_write_tokens", usage.get("cacheCreationInputTokens", 0), "tokens", tag))
                metrics.append(MetricPoint("claude_code_cost_usd", usage.get("costUSD", 0), "USD", tag))

        # Daily activity (last 7 days)
        daily = data.get("dailyActivity", [])
        if daily:
            latest = daily[-1]
            metrics.append(MetricPoint("claude_code_daily_messages", latest.get("messageCount", 0), "count"))
            metrics.append(MetricPoint("claude_code_daily_sessions", latest.get("sessionCount", 0), "count"))
            metrics.append(MetricPoint("claude_code_daily_tool_calls", latest.get("toolCallCount", 0), "count"))

        # Daily model tokens
        daily_tokens = data.get("dailyModelTokens", [])
        if daily_tokens:
            latest = daily_tokens[-1]
            tokens_by_model = latest.get("tokensByModel", {})
            for model, tokens in tokens_by_model.items():
                metrics.append(MetricPoint("claude_code_daily_tokens", tokens, "tokens", {"model": model}))

        # Longest session
        longest = data.get("longestSession", {})
        if longest:
            metrics.append(MetricPoint("claude_code_longest_session_duration", longest.get("duration", 0), "ms"))
            metrics.append(MetricPoint("claude_code_longest_session_messages", longest.get("messageCount", 0), "count"))

    def _collect_history(self, path: Path, metrics: list[MetricPoint]) -> None:
        """Tail history.jsonl for new interactions."""
        try:
            file_size = path.stat().st_size
        except OSError:
            return

        if file_size < self._history_pos:
            # File was truncated/rotated
            self._history_pos = 0

        new_interactions = 0
        sessions_seen: set[str] = set()
        projects_seen: set[str] = set()

        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                f.seek(self._history_pos)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        new_interactions += 1
                        sid = entry.get("sessionId")
                        if sid:
                            sessions_seen.add(sid)
                        project = entry.get("project")
                        if project:
                            projects_seen.add(project)
                    except json.JSONDecodeError:
                        continue
                self._history_pos = f.tell()
        except OSError:
            return

        if new_interactions > 0:
            metrics.append(MetricPoint("claude_code_new_interactions", new_interactions, "count"))
            metrics.append(MetricPoint("claude_code_active_sessions", len(sessions_seen), "count"))
            metrics.append(MetricPoint("claude_code_active_projects", len(projects_seen), "count"))

    def _collect_telemetry(self, telemetry_dir: Path, metrics: list[MetricPoint]) -> None:
        """Count recent telemetry error files."""
        error_files = list(telemetry_dir.glob("1p_failed_events.*.json"))
        metrics.append(MetricPoint("claude_code_telemetry_error_files", len(error_files), "count"))

        # Count errors in recent files (last 10 minutes)
        recent_errors = 0
        cutoff = time.time() - 600
        for f in error_files:
            try:
                if f.stat().st_mtime > cutoff:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        recent_errors += len(data)
                    elif isinstance(data, dict):
                        recent_errors += 1
            except (json.JSONDecodeError, OSError):
                continue

        metrics.append(MetricPoint("claude_code_recent_errors", recent_errors, "count"))
