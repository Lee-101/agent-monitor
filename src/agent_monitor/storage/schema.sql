CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collector TEXT NOT NULL,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    tags TEXT,
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_collector_time ON metrics(collector, timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_name_time ON metrics(name, timestamp);

CREATE TABLE IF NOT EXISTS agent_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    is_running INTEGER NOT NULL,
    pid INTEGER,
    cpu_percent REAL,
    memory_rss_bytes INTEGER,
    memory_percent REAL,
    active_sessions INTEGER DEFAULT 0,
    total_messages INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    details TEXT,
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_agent_time ON agent_snapshots(agent_name, timestamp);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    source TEXT,
    acknowledged INTEGER DEFAULT 0,
    triggered_at REAL NOT NULL,
    resolved_at REAL
);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity, triggered_at);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    source TEXT,
    details TEXT,
    timestamp REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics_hourly (
    collector TEXT NOT NULL,
    name TEXT NOT NULL,
    hour_ts REAL NOT NULL,
    avg_value REAL,
    min_value REAL,
    max_value REAL,
    sample_count INTEGER,
    PRIMARY KEY (collector, name, hour_ts)
);
