"""FastAPI application - ties together REST, WebSocket, and dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse

from ..config import AppConfig
from ..collectors.registry import CollectorRegistry
from ..storage.sqlite_store import SQLiteStore
from .websocket import WebSocketManager
from .routes.system import create_system_router
from .routes.agents import create_agents_router
from .routes.alerts import create_alerts_router
from .routes.history import create_history_router

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"


def create_app(config: AppConfig, registry: CollectorRegistry, store: SQLiteStore) -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title=config.dashboard.title,
        description="Device and agent framework monitoring",
        version="0.1.0",
    )

    # Templates
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # WebSocket manager
    ws_manager = WebSocketManager(registry)

    @app.on_event("startup")
    async def on_startup():
        ws_manager.start(interval=config.dashboard.refresh_interval_ms / 1000)

    @app.on_event("shutdown")
    async def on_shutdown():
        await ws_manager.stop()

    # Register API routes
    app.include_router(create_system_router(registry, store))
    app.include_router(create_agents_router(registry, store))
    app.include_router(create_alerts_router(store))
    app.include_router(create_history_router(registry, store))

    # WebSocket endpoint
    @app.websocket("/ws/live")
    async def websocket_endpoint(websocket: WebSocket):
        await ws_manager.connect(websocket)
        try:
            while True:
                # Keep connection alive, receive client messages if any
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    # Dashboard pages
    @app.get("/", response_class=HTMLResponse)
    async def dashboard_index(request: Request):
        try:
            return templates.TemplateResponse(
                request=request,
                name="index.html",
                context={
                    "title": config.dashboard.title,
                    "refresh_ms": config.dashboard.refresh_interval_ms,
                },
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return HTMLResponse(f"<h1>Error</h1><pre>{e}</pre>", status_code=500)

    @app.get("/agents/{name}", response_class=HTMLResponse)
    async def dashboard_agent(request: Request, name: str):
        try:
            return templates.TemplateResponse(
                request=request,
                name="agents.html",
                context={
                    "title": f"{name} - {config.dashboard.title}",
                    "agent_name": name,
                    "refresh_ms": config.dashboard.refresh_interval_ms,
                },
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return HTMLResponse(f"<h1>Error</h1><pre>{e}</pre>", status_code=500)

    @app.get("/history", response_class=HTMLResponse)
    async def dashboard_history(request: Request):
        try:
            return templates.TemplateResponse(
                request=request,
                name="history.html",
                context={
                    "title": f"History - {config.dashboard.title}",
                    "refresh_ms": config.dashboard.refresh_interval_ms,
                },
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return HTMLResponse(f"<h1>Error</h1><pre>{e}</pre>", status_code=500)

    return app
