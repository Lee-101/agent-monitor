"""System metrics collector - CPU, memory, disk, network, temperature."""

from __future__ import annotations

import platform
import time

import psutil

from .base import BaseCollector, CollectorResult, MetricPoint


class SystemCollector(BaseCollector):
    """Collects CPU, memory, disk, network, and temperature metrics."""

    _prev_disk_io: tuple | None = None
    _prev_net_io: tuple | None = None
    _prev_time: float = 0

    @property
    def name(self) -> str:
        return "system"

    def is_available(self) -> bool:
        return True  # psutil is always available

    async def collect(self) -> CollectorResult:
        metrics: list[MetricPoint] = []
        now = time.time()
        dt = now - self._prev_time if self._prev_time > 0 else 1.0
        self._prev_time = now

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0, percpu=True)
        for i, pct in enumerate(cpu_percent):
            metrics.append(MetricPoint("cpu_percent", pct, "%", {"core": str(i)}))
        metrics.append(MetricPoint("cpu_percent_avg", sum(cpu_percent) / len(cpu_percent), "%"))

        freq = psutil.cpu_freq()
        if freq:
            metrics.append(MetricPoint("cpu_freq_current", freq.current, "MHz"))
            if freq.max:
                metrics.append(MetricPoint("cpu_freq_max", freq.max, "MHz"))

        load = psutil.getloadavg() if hasattr(psutil, "getloadavg") else None
        if load:
            for i, name in enumerate(["1m", "5m", "15m"]):
                metrics.append(MetricPoint(f"load_avg_{name}", load[i], ""))

        # Memory
        mem = psutil.virtual_memory()
        metrics.append(MetricPoint("memory_total", mem.total, "bytes"))
        metrics.append(MetricPoint("memory_available", mem.available, "bytes"))
        metrics.append(MetricPoint("memory_used", mem.used, "bytes"))
        metrics.append(MetricPoint("memory_percent", mem.percent, "%"))

        swap = psutil.swap_memory()
        metrics.append(MetricPoint("swap_total", swap.total, "bytes"))
        metrics.append(MetricPoint("swap_used", swap.used, "bytes"))
        metrics.append(MetricPoint("swap_percent", swap.percent, "%"))

        # Disk
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                tag = {"mountpoint": part.mountpoint, "device": part.device}
                metrics.append(MetricPoint("disk_total", usage.total, "bytes", tag))
                metrics.append(MetricPoint("disk_used", usage.used, "bytes", tag))
                metrics.append(MetricPoint("disk_free", usage.free, "bytes", tag))
                metrics.append(MetricPoint("disk_percent", usage.percent, "%", tag))
            except (PermissionError, OSError):
                pass

        # Disk I/O
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io and self._prev_disk_io:
                prev = self._prev_disk_io
                metrics.append(MetricPoint("disk_read_bytes_sec", (disk_io.read_bytes - prev[0]) / dt, "bytes/s"))
                metrics.append(MetricPoint("disk_write_bytes_sec", (disk_io.write_bytes - prev[1]) / dt, "bytes/s"))
            if disk_io:
                self._prev_disk_io = (disk_io.read_bytes, disk_io.write_bytes)
        except Exception:
            pass

        # Network
        net_io = psutil.net_io_counters()
        if net_io:
            metrics.append(MetricPoint("net_bytes_sent", net_io.bytes_sent, "bytes"))
            metrics.append(MetricPoint("net_bytes_recv", net_io.bytes_recv, "bytes"))
            if self._prev_net_io:
                prev = self._prev_net_io
                metrics.append(MetricPoint("net_send_bytes_sec", (net_io.bytes_sent - prev[0]) / dt, "bytes/s"))
                metrics.append(MetricPoint("net_recv_bytes_sec", (net_io.bytes_recv - prev[1]) / dt, "bytes/s"))
            self._prev_net_io = (net_io.bytes_sent, net_io.bytes_recv)

        # Temperature
        temp = self._read_temperature()
        if temp is not None:
            metrics.append(MetricPoint("cpu_temperature", temp, "celsius"))

        return CollectorResult(collector_name=self.name, metrics=metrics, status="ok")

    def _read_temperature(self) -> float | None:
        """Read CPU temperature with platform-specific fallbacks."""
        # Try psutil sensors
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Pick first available sensor
                for name, entries in temps.items():
                    if entries:
                        return entries[0].current
        except (AttributeError, Exception):
            pass

        # Windows: try WMI (requires admin, may not work)
        if platform.system() == "Windows":
            try:
                import wmi
                w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                sensors = w.Sensor()
                for sensor in sensors:
                    if sensor.SensorType == "Temperature" and "CPU" in sensor.Name:
                        return float(sensor.Value)
            except Exception:
                pass

        return None
