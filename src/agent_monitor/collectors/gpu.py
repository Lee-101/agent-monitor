"""NVIDIA GPU metrics collector via nvidia-smi."""

from __future__ import annotations

import csv
import io
import logging
import subprocess

from .base import BaseCollector, CollectorResult, MetricPoint

logger = logging.getLogger(__name__)

QUERY_PARAMS = [
    "utilization.gpu",
    "utilization.memory",
    "memory.total",
    "memory.used",
    "memory.free",
    "temperature.gpu",
    "power.draw",
    "power.limit",
    "fan.speed",
    "name",
    "uuid",
]


class GpuCollector(BaseCollector):
    """Collects NVIDIA GPU metrics via nvidia-smi."""

    @property
    def name(self) -> str:
        return "gpu"

    def is_available(self) -> bool:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def collect(self) -> CollectorResult:
        metrics: list[MetricPoint] = []

        query = ",".join(QUERY_PARAMS)
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return CollectorResult(
                collector_name=self.name, metrics=[], status="error",
                error_message=result.stderr.strip(),
            )

        reader = csv.reader(io.StringIO(result.stdout))
        for row in reader:
            if len(row) < len(QUERY_PARAMS):
                continue
            gpu_name = row[9].strip()
            gpu_uuid = row[10].strip()
            tag = {"gpu": gpu_name, "uuid": gpu_uuid}

            def safe_float(val: str) -> float | None:
                try:
                    v = val.strip()
                    if v in ("[N/A]", "N/A", ""):
                        return None
                    return float(v)
                except ValueError:
                    return None

            gpu_util = safe_float(row[0])
            if gpu_util is not None:
                metrics.append(MetricPoint("gpu_utilization", gpu_util, "%", tag))

            mem_util = safe_float(row[1])
            if mem_util is not None:
                metrics.append(MetricPoint("gpu_memory_utilization", mem_util, "%", tag))

            for metric_name, idx in [("gpu_memory_total", 2), ("gpu_memory_used", 3), ("gpu_memory_free", 4)]:
                val = safe_float(row[idx])
                if val is not None:
                    metrics.append(MetricPoint(metric_name, val * 1024 * 1024, "bytes", tag))

            temp = safe_float(row[5])
            if temp is not None:
                metrics.append(MetricPoint("gpu_temperature", temp, "celsius", tag))

            power_draw = safe_float(row[6])
            if power_draw is not None:
                metrics.append(MetricPoint("gpu_power_draw", power_draw, "watts", tag))

            power_limit = safe_float(row[7])
            if power_limit is not None:
                metrics.append(MetricPoint("gpu_power_limit", power_limit, "watts", tag))

            fan = safe_float(row[8])
            if fan is not None:
                metrics.append(MetricPoint("gpu_fan_speed", fan, "%", tag))

        # Per-process GPU memory
        try:
            proc_result = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid,used_memory,name", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if proc_result.returncode == 0:
                for row in csv.reader(io.StringIO(proc_result.stdout)):
                    if len(row) >= 2:
                        pid = row[0].strip()
                        mem = safe_float(row[1])
                        proc_name = row[2].strip() if len(row) > 2 else ""
                        if mem is not None:
                            metrics.append(MetricPoint(
                                "gpu_process_memory", mem * 1024 * 1024, "bytes",
                                {"pid": pid, "process": proc_name},
                            ))
        except Exception:
            pass

        return CollectorResult(collector_name=self.name, metrics=metrics, status="ok")
