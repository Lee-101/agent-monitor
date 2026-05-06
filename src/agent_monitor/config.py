"""Configuration loading from YAML file with environment variable overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8501
    debug: bool = False


@dataclass
class CollectorConfig:
    enabled: bool = True
    interval_seconds: float = 5.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StorageConfig:
    database_path: str = "./data/monitor.db"
    retention_days: int = 90
    aggregation_enabled: bool = True


@dataclass
class AlertingConfig:
    enabled: bool = True
    rules_file: str = "./alert_rules.yaml"
    notifiers: list[dict[str, Any]] = field(default_factory=lambda: [
        {"type": "log", "path": "./data/alerts.log"}
    ])


@dataclass
class DashboardConfig:
    title: str = "Agent Monitor"
    refresh_interval_ms: int = 2000


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    collectors: dict[str, CollectorConfig] = field(default_factory=dict)
    storage: StorageConfig = field(default_factory=StorageConfig)
    alerting: AlertingConfig = field(default_factory=AlertingConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursively for nested dicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file with sensible defaults."""
    app = AppConfig()

    # Find config file
    if config_path is None:
        candidates = [
            Path.cwd() / "agent-monitor.yaml",
            app.base_dir / "agent-monitor.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    # Load YAML if found
    raw: dict[str, Any] = {}
    if config_path and Path(config_path).exists():
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    # Apply to dataclasses
    if "server" in raw:
        app.server = ServerConfig(**raw["server"])

    if "collectors" in raw:
        for name, cfg in raw["collectors"].items():
            if isinstance(cfg, dict):
                enabled = cfg.pop("enabled", True)
                interval = cfg.pop("interval_seconds", 5.0)
                app.collectors[name] = CollectorConfig(
                    enabled=enabled, interval_seconds=interval, extra=cfg
                )
            else:
                app.collectors[name] = CollectorConfig(enabled=bool(cfg))

    if "storage" in raw:
        app.storage = StorageConfig(**raw["storage"])

    if "alerting" in raw:
        app.alerting = AlertingConfig(**raw["alerting"])

    if "dashboard" in raw:
        app.dashboard = DashboardConfig(**raw["dashboard"])

    # Environment variable overrides
    env_port = os.environ.get("AGENT_MONITOR_PORT")
    if env_port:
        app.server.port = int(env_port)

    env_host = os.environ.get("AGENT_MONITOR_HOST")
    if env_host:
        app.server.host = env_host

    env_db = os.environ.get("AGENT_MONITOR_DB")
    if env_db:
        app.storage.database_path = env_db

    return app
