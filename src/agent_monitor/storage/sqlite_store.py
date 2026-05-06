"""SQLite storage backend with WAL mode, schema migration, and aggregation."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..collectors.base import CollectorResult, MetricPoint

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class SQLiteStore:
    """SQLite-based storage for metrics, snapshots, and alerts."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Open connection and initialize schema."""
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _init_schema(self) -> None:
        """Create tables if needed, run migrations."""
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, encoding="utf-8") as f:
            self._conn.executescript(f.read())

        # Check/set schema version
        cur = self._conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = cur.fetchone()
        if row is None:
            self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            self._conn.commit()
        elif row[0] < SCHEMA_VERSION:
            self._run_migrations(row[0])
        logger.info("Database initialized at %s (version=%s)", self.db_path, SCHEMA_VERSION)

    def _run_migrations(self, from_version: int) -> None:
        """Run schema migrations from from_version to SCHEMA_VERSION."""
        # Future migrations go here
        self._conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        self._conn.commit()

    def store_metrics(self, result: CollectorResult) -> None:
        """Store metrics from a collector result."""
        if not result.metrics:
            return
        rows = [
            (m.name, m.value, m.unit, json.dumps(m.tags) if m.tags else None, m.timestamp)
            for m in result.metrics
        ]
        self._conn.executemany(
            "INSERT INTO metrics (collector, name, value, unit, tags, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            [(result.collector_name, *r) for r in rows],
        )
        self._conn.commit()

    def store_agent_snapshot(
        self,
        agent_name: str,
        is_running: bool,
        pid: int | None = None,
        cpu_percent: float | None = None,
        memory_rss_bytes: int | None = None,
        memory_percent: float | None = None,
        active_sessions: int = 0,
        total_messages: int = 0,
        error_count: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Store an agent status snapshot."""
        self._conn.execute(
            """INSERT INTO agent_snapshots
            (agent_name, is_running, pid, cpu_percent, memory_rss_bytes, memory_percent,
             active_sessions, total_messages, error_count, details, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_name, int(is_running), pid, cpu_percent, memory_rss_bytes,
                memory_percent, active_sessions, total_messages, error_count,
                json.dumps(details) if details else None, time.time(),
            ),
        )
        self._conn.commit()

    def store_alert(
        self, rule_name: str, severity: str, message: str, source: str | None = None
    ) -> int:
        """Store an alert event. Returns the alert ID."""
        cur = self._conn.execute(
            """INSERT INTO alerts (rule_name, severity, message, source, triggered_at)
            VALUES (?, ?, ?, ?, ?)""",
            (rule_name, severity, message, source, time.time()),
        )
        self._conn.commit()
        return cur.lastrowid

    def acknowledge_alert(self, alert_id: int) -> bool:
        """Mark an alert as acknowledged."""
        cur = self._conn.execute(
            "UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_latest_metrics(self, collector: str, minutes: int = 30) -> list[dict]:
        """Get recent metrics for a collector."""
        since = time.time() - minutes * 60
        cur = self._conn.execute(
            """SELECT name, value, unit, tags, timestamp FROM metrics
            WHERE collector = ? AND timestamp > ? ORDER BY timestamp""",
            (collector, since),
        )
        return [
            {"name": r[0], "value": r[1], "unit": r[2], "tags": json.loads(r[3]) if r[3] else {}, "timestamp": r[4]}
            for r in cur.fetchall()
        ]

    def get_latest_snapshots(self, agent_name: str | None = None, limit: int = 100) -> list[dict]:
        """Get recent agent snapshots."""
        if agent_name:
            cur = self._conn.execute(
                """SELECT agent_name, is_running, pid, cpu_percent, memory_rss_bytes,
                active_sessions, total_messages, error_count, details, timestamp
                FROM agent_snapshots WHERE agent_name = ? ORDER BY timestamp DESC LIMIT ?""",
                (agent_name, limit),
            )
        else:
            cur = self._conn.execute(
                """SELECT agent_name, is_running, pid, cpu_percent, memory_rss_bytes,
                active_sessions, total_messages, error_count, details, timestamp
                FROM agent_snapshots ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            )
        return [
            {
                "agent_name": r[0], "is_running": bool(r[1]), "pid": r[2],
                "cpu_percent": r[3], "memory_rss_bytes": r[4],
                "active_sessions": r[5], "total_messages": r[6],
                "error_count": r[7], "details": json.loads(r[8]) if r[8] else {},
                "timestamp": r[9],
            }
            for r in cur.fetchall()
        ]

    def get_alerts(self, severity: str | None = None, acknowledged: bool | None = None, limit: int = 50) -> list[dict]:
        """Get alerts with optional filters."""
        query = "SELECT id, rule_name, severity, message, source, acknowledged, triggered_at, resolved_at FROM alerts"
        conditions = []
        params: list[Any] = []
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        if acknowledged is not None:
            conditions.append("acknowledged = ?")
            params.append(int(acknowledged))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY triggered_at DESC LIMIT ?"
        params.append(limit)
        cur = self._conn.execute(query, params)
        return [
            {
                "id": r[0], "rule_name": r[1], "severity": r[2], "message": r[3],
                "source": r[4], "acknowledged": bool(r[5]), "triggered_at": r[6],
                "resolved_at": r[7],
            }
            for r in cur.fetchall()
        ]

    def aggregate_hourly(self) -> None:
        """Aggregate raw metrics into hourly buckets."""
        cutoff = time.time() - 7200  # 2 hours ago
        self._conn.execute(
            """INSERT OR REPLACE INTO metrics_hourly (collector, name, hour_ts, avg_value, min_value, max_value, sample_count)
            SELECT collector, name,
                   CAST(timestamp / 3600 AS INTEGER) * 3600 AS hour_ts,
                   AVG(value), MIN(value), MAX(value), COUNT(*)
            FROM metrics
            WHERE timestamp < ?
            GROUP BY collector, name, hour_ts""",
            (cutoff,),
        )
        self._conn.commit()

    def cleanup_old_data(self, retention_days: int = 90) -> None:
        """Delete data older than retention_days."""
        cutoff = time.time() - retention_days * 86400
        self._conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
        self._conn.execute("DELETE FROM agent_snapshots WHERE timestamp < ?", (cutoff,))
        self._conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        self._conn.commit()
        logger.info("Cleaned up data older than %s days", retention_days)
