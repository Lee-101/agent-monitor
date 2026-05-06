"""Application entry point - CLI and server startup."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from .config import load_config, AppConfig
from .collectors.registry import CollectorRegistry
from .collectors.system import SystemCollector
from .collectors.gpu import GpuCollector
from .collectors.process import ProcessCollector
from .collectors.hermes import HermesCollector
from .collectors.claude_code import ClaudeCodeCollector
from .collectors.openclaw import OpenClawCollector
from .collectors.codex import CodexCollector
from .storage.sqlite_store import SQLiteStore
from .alerting.engine import AlertEngine

logger = logging.getLogger("agent_monitor")


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def create_registry(config: AppConfig) -> CollectorRegistry:
    """Create and populate the collector registry based on config."""
    registry = CollectorRegistry()

    # System collector (always enabled)
    sys_cfg = config.collectors.get("system")
    if sys_cfg is None or sys_cfg.enabled:
        interval = sys_cfg.interval_seconds if sys_cfg else 2.0
        registry.register(SystemCollector(), interval)

    # GPU collector
    gpu_cfg = config.collectors.get("gpu")
    if gpu_cfg is None or gpu_cfg.enabled:
        interval = gpu_cfg.interval_seconds if gpu_cfg else 5.0
        registry.register(GpuCollector(), interval)

    # Process collector
    proc_cfg = config.collectors.get("process")
    if proc_cfg is None or proc_cfg.enabled:
        interval = proc_cfg.interval_seconds if proc_cfg else 5.0
        registry.register(ProcessCollector(), interval)

    # Agent-specific collectors
    hermes_cfg = config.collectors.get("hermes")
    if hermes_cfg is None or hermes_cfg.enabled:
        interval = hermes_cfg.interval_seconds if hermes_cfg else 10.0
        registry.register(HermesCollector(), interval)

    claude_cfg = config.collectors.get("claude_code")
    if claude_cfg is None or claude_cfg.enabled:
        interval = claude_cfg.interval_seconds if claude_cfg else 10.0
        registry.register(ClaudeCodeCollector(), interval)

    openclaw_cfg = config.collectors.get("openclaw")
    if openclaw_cfg is None or openclaw_cfg.enabled:
        interval = openclaw_cfg.interval_seconds if openclaw_cfg else 10.0
        registry.register(OpenClawCollector(), interval)

    codex_cfg = config.collectors.get("codex")
    if codex_cfg is None or codex_cfg.enabled:
        interval = codex_cfg.interval_seconds if codex_cfg else 10.0
        registry.register(CodexCollector(), interval)

    return registry


async def run_server(config: AppConfig) -> None:
    """Start the monitoring server."""
    import uvicorn

    # Initialize storage
    db_path = config.base_dir / config.storage.database_path
    store = SQLiteStore(db_path)
    store.connect()

    # Create collector registry
    registry = create_registry(config)

    # Store results callback
    def on_result(collector_name: str, result):
        store.store_metrics(result)

    registry.on_result(on_result)

    # Alert engine
    alert_engine = None
    if config.alerting.enabled:
        rules_path = config.base_dir / config.alerting.rules_file
        alert_engine = AlertEngine(
            registry=registry,
            store=store,
            rules_path=rules_path,
            notifier_configs=config.alerting.notifiers,
        )

    # Import and create FastAPI app
    from .api.server import create_app
    app = create_app(config, registry, store)

    # Start collectors and alert engine
    await registry.start_all()
    if alert_engine:
        alert_engine.start()

    # Run uvicorn
    uvi_config = uvicorn.Config(
        app,
        host=config.server.host,
        port=config.server.port,
        log_level="debug" if config.server.debug else "info",
    )
    server = uvicorn.Server(uvi_config)

    # Handle shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(_shutdown(server, registry, store)))
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    logger.info("Starting Agent Monitor on http://%s:%s", config.server.host, config.server.port)
    await server.serve()


async def _shutdown(server, registry, store, alert_engine=None):
    logger.info("Shutting down...")
    if alert_engine:
        await alert_engine.stop()
    await registry.stop_all()
    store.close()
    server.should_exit = True


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Agent Monitor - Device and agent framework monitoring")
    parser.add_argument("-c", "--config", help="Path to config file", default=None)
    parser.add_argument("-p", "--port", type=int, help="Server port", default=None)
    parser.add_argument("--host", help="Server host", default=None)
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(args.debug)
    config = load_config(args.config)

    if args.port:
        config.server.port = args.port
    if args.host:
        config.server.host = args.host
    if args.debug:
        config.server.debug = True

    asyncio.run(run_server(config))


if __name__ == "__main__":
    main()
