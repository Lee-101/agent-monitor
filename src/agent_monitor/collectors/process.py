"""Process-level monitoring for agent frameworks."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import psutil

from .base import BaseCollector, CollectorResult, MetricPoint

logger = logging.getLogger(__name__)

# Default process patterns to monitor
DEFAULT_WATCH_LIST = [
    {"name": "claude_code", "match": "claude.exe"},
    {"name": "hermes", "match": "run_agent.py"},
    {"name": "hermes_cli", "match": "cli.py"},
    {"name": "openclaw", "match": "openclaw"},
]


@dataclass
class ProcessInfo:
    """Information about a monitored process."""
    name: str
    pid: int
    cpu_percent: float = 0.0
    memory_rss: int = 0
    memory_percent: float = 0.0
    threads: int = 0
    status: str = ""
    create_time: float = 0.0
    cmdline: str = ""


class ProcessCollector(BaseCollector):
    """Monitors specific agent processes by name or command line pattern."""

    def __init__(self, watch_list: list[dict] | None = None) -> None:
        self._watch_list = watch_list or DEFAULT_WATCH_LIST
        self._pid_cache: dict[str, set[int]] = {}

    @property
    def name(self) -> str:
        return "process"

    def is_available(self) -> bool:
        return True

    def _find_processes(self, pattern: str) -> list[psutil.Process]:
        """Find processes matching a name or cmdline pattern."""
        found = []
        pattern_lower = pattern.lower()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                info = proc.info
                name = (info.get("name") or "").lower()
                cmdline = " ".join(info.get("cmdline") or []).lower()
                if pattern_lower in name or pattern_lower in cmdline:
                    found.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found

    async def collect(self) -> CollectorResult:
        metrics: list[MetricPoint] = []
        now = time.time()

        for watch in self._watch_list:
            agent_name = watch["name"]
            pattern = watch["match"]
            procs = self._find_processes(pattern)

            if not procs:
                metrics.append(MetricPoint("process_running", 0, "bool", {"agent": agent_name}))
                continue

            for proc in procs:
                try:
                    info = proc.as_dict(attrs=[
                        "pid", "cpu_percent", "memory_info", "memory_percent",
                        "num_threads", "status", "create_time", "cmdline",
                    ])
                    pid = info["pid"]
                    tag = {"agent": agent_name, "pid": str(pid)}

                    metrics.append(MetricPoint("process_running", 1, "bool", {"agent": agent_name}))
                    metrics.append(MetricPoint("process_cpu_percent", info.get("cpu_percent", 0), "%", tag))

                    mem_info = info.get("memory_info")
                    if mem_info:
                        metrics.append(MetricPoint("process_memory_rss", mem_info.rss, "bytes", tag))
                        metrics.append(MetricPoint("process_memory_vms", mem_info.vms, "bytes", tag))

                    metrics.append(MetricPoint("process_memory_percent", info.get("memory_percent", 0), "%", tag))
                    metrics.append(MetricPoint("process_threads", info.get("num_threads", 0), "count", tag))

                    create_time = info.get("create_time", 0)
                    if create_time:
                        uptime = now - create_time
                        metrics.append(MetricPoint("process_uptime", uptime, "seconds", tag))

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        return CollectorResult(collector_name=self.name, metrics=metrics, status="ok")

    def get_process_info(self, agent_name: str) -> list[ProcessInfo]:
        """Get detailed process info for a specific agent."""
        for watch in self._watch_list:
            if watch["name"] == agent_name:
                procs = self._find_processes(watch["match"])
                result = []
                for proc in procs:
                    try:
                        info = proc.as_dict(attrs=[
                            "pid", "cpu_percent", "memory_info", "memory_percent",
                            "num_threads", "status", "create_time", "cmdline",
                        ])
                        result.append(ProcessInfo(
                            name=agent_name,
                            pid=info["pid"],
                            cpu_percent=info.get("cpu_percent", 0),
                            memory_rss=info["memory_info"].rss if info.get("memory_info") else 0,
                            memory_percent=info.get("memory_percent", 0),
                            threads=info.get("num_threads", 0),
                            status=info.get("status", ""),
                            create_time=info.get("create_time", 0),
                            cmdline=" ".join(info.get("cmdline") or []),
                        ))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                return result
        return []
