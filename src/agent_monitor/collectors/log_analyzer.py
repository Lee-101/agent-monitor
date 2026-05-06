"""General-purpose log tail and pattern matching module."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Common log level patterns
LEVEL_PATTERN = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d]*)\s+"
    r"(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b",
    re.IGNORECASE,
)

SIMPLE_LEVEL_PATTERN = re.compile(
    r"\b(?P<level>ERROR|WARNING|WARN|CRITICAL|FATAL)\b",
    re.IGNORECASE,
)


@dataclass
class LogEntry:
    """A parsed log entry."""
    timestamp: str = ""
    level: str = ""
    message: str = ""
    raw: str = ""
    line_number: int = 0


@dataclass
class LogAnalysisResult:
    """Result of analyzing a log file."""
    file_path: str
    total_lines: int = 0
    new_lines: int = 0
    error_count: int = 0
    warning_count: int = 0
    recent_errors: list[LogEntry] = field(default_factory=list)
    recent_warnings: list[LogEntry] = field(default_factory=list)
    errors_per_minute: float = 0.0
    warnings_per_minute: float = 0.0


class LogAnalyzer:
    """Tails log files and extracts structured information.

    Uses seek-based incremental reading to avoid re-reading entire files.
    Supports rotated log detection.
    """

    def __init__(self, max_recent: int = 50) -> None:
        self._positions: dict[str, int] = {}
        self._last_sizes: dict[str, int] = {}
        self._error_timestamps: dict[str, list[float]] = {}
        self._warn_timestamps: dict[str, list[float]] = {}
        self._max_recent = max_recent

    def analyze(self, file_path: str | Path, window_minutes: int = 5) -> LogAnalysisResult:
        """Analyze a log file from the last known position."""
        path = Path(file_path)
        result = LogAnalysisResult(file_path=str(path))

        if not path.exists():
            return result

        try:
            current_size = path.stat().st_size
        except OSError:
            return result

        last_size = self._last_sizes.get(str(path), 0)
        last_pos = self._positions.get(str(path), 0)

        # Detect log rotation (file shrunk)
        if current_size < last_size:
            last_pos = 0
            logger.info("Log rotation detected for %s", path)

        self._last_sizes[str(path)] = current_size

        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                f.seek(last_pos)
                new_lines = f.readlines()
                self._positions[str(path)] = f.tell()
        except (OSError, PermissionError) as e:
            logger.warning("Cannot read log file %s: %s", path, e)
            return result

        result.new_lines = len(new_lines)

        now = time.time()
        cutoff = now - window_minutes * 60
        path_key = str(path)

        # Initialize timestamp lists
        if path_key not in self._error_timestamps:
            self._error_timestamps[path_key] = []
        if path_key not in self._warn_timestamps:
            self._warn_timestamps[path_key] = []

        error_ts = self._error_timestamps[path_key]
        warn_ts = self._warn_timestamps[path_key]

        for i, line in enumerate(new_lines):
            entry = self._parse_line(line, last_pos + i + 1)

            if entry.level in ("ERROR", "CRITICAL", "FATAL"):
                result.error_count += 1
                error_ts.append(now)
                if len(result.recent_errors) < self._max_recent:
                    result.recent_errors.append(entry)
            elif entry.level in ("WARNING", "WARN"):
                result.warning_count += 1
                warn_ts.append(now)
                if len(result.recent_warnings) < self._max_recent:
                    result.recent_warnings.append(entry)

        # Calculate rates
        error_ts[:] = [t for t in error_ts if t > cutoff]
        warn_ts[:] = [t for t in warn_ts if t > cutoff]

        if window_minutes > 0:
            result.errors_per_minute = len(error_ts) / window_minutes
            result.warnings_per_minute = len(warn_ts) / window_minutes

        return result

    def _parse_line(self, line: str, line_number: int) -> LogEntry:
        """Parse a single log line into a LogEntry."""
        entry = LogEntry(raw=line.rstrip(), line_number=line_number)

        match = LEVEL_PATTERN.search(line)
        if match:
            entry.timestamp = match.group("timestamp")
            entry.level = match.group("level").upper()
            # Normalize WARN -> WARNING
            if entry.level == "WARN":
                entry.level = "WARNING"
            # Extract message after the level
            msg_start = match.end()
            entry.message = line[msg_start:].strip()
        else:
            # Fallback: just detect level anywhere
            match = SIMPLE_LEVEL_PATTERN.search(line)
            if match:
                entry.level = match.group("level").upper()
                if entry.level == "WARN":
                    entry.level = "WARNING"

        return entry

    def reset(self, file_path: str | Path | None = None) -> None:
        """Reset tracking for a file or all files."""
        if file_path:
            key = str(file_path)
            self._positions.pop(key, None)
            self._last_sizes.pop(key, None)
            self._error_timestamps.pop(key, None)
            self._warn_timestamps.pop(key, None)
        else:
            self._positions.clear()
            self._last_sizes.clear()
            self._error_timestamps.clear()
            self._warn_timestamps.clear()
