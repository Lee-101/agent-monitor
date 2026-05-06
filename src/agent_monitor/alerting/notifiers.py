"""Notification backends for alerts."""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BaseNotifier(ABC):
    """Abstract base for alert notifiers."""

    @abstractmethod
    def notify(self, rule_name: str, severity: str, message: str, source: str | None = None) -> None:
        """Send a notification."""


class LogNotifier(BaseNotifier):
    """Writes alerts to a log file."""

    def __init__(self, log_path: str | Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def notify(self, rule_name: str, severity: str, message: str, source: str | None = None) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{severity.upper()}] [{rule_name}] {message}"
        if source:
            line += f" (source: {source})"
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.error("Failed to write alert log: %s", e)


class DesktopNotifier(BaseNotifier):
    """Sends desktop notifications (Windows toast / cross-platform)."""

    def __init__(self) -> None:
        self._available = False
        try:
            import plyer
            self._plyer = plyer
            self._available = True
        except ImportError:
            self._plyer = None

    def notify(self, rule_name: str, severity: str, message: str, source: str | None = None) -> None:
        if not self._available:
            logger.debug("Desktop notifications not available (plyer not installed)")
            return

        title = f"Agent Monitor [{severity.upper()}]"
        body = f"{message}"
        if source:
            body += f"\n来源: {source}"

        try:
            self._plyer.notification.notify(
                title=title,
                message=body,
                timeout=10,
            )
        except Exception as e:
            logger.warning("Desktop notification failed: %s", e)


class WebhookNotifier(BaseNotifier):
    """Sends alerts to a webhook URL via HTTP POST."""

    def __init__(self, url: str) -> None:
        self.url = url

    def notify(self, rule_name: str, severity: str, message: str, source: str | None = None) -> None:
        import urllib.request

        payload = json.dumps({
            "rule_name": rule_name,
            "severity": severity,
            "message": message,
            "source": source,
            "timestamp": time.time(),
        })

        try:
            req = urllib.request.Request(
                self.url,
                data=payload.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            logger.warning("Webhook notification failed: %s", e)


class ConsoleNotifier(BaseNotifier):
    """Prints alerts to console (stderr)."""

    def notify(self, rule_name: str, severity: str, message: str, source: str | None = None) -> None:
        prefix = {"info": "INFO", "warning": "WARN", "critical": "CRIT"}.get(severity, "ALERT")
        logger.warning("[%s] %s: %s%s", prefix, rule_name, message, f" ({source})" if source else "")


def create_notifiers(config: list[dict[str, Any]]) -> list[BaseNotifier]:
    """Create notifier instances from configuration."""
    notifiers: list[BaseNotifier] = []

    # Always add console notifier
    notifiers.append(ConsoleNotifier())

    for cfg in config:
        notifier_type = cfg.get("type", "")
        if notifier_type == "log":
            notifiers.append(LogNotifier(cfg.get("path", "./data/alerts.log")))
        elif notifier_type == "desktop":
            notifiers.append(DesktopNotifier())
        elif notifier_type == "webhook":
            url = cfg.get("url")
            if url:
                notifiers.append(WebhookNotifier(url))

    return notifiers
