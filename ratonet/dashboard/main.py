"""FastAPI application principal do RatoNet Dashboard."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ratonet.common.logger import get_logger
from ratonet.config import settings
from ratonet.dashboard import db
from ratonet.dashboard.admin import admin_router
from ratonet.dashboard.routes import router
from ratonet.dashboard.ws_handler import manager

log = get_logger("dashboard")

STATIC_DIR = Path(settings.dashboard.static_dir).resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown da aplicação."""
    # Inicializa banco de dados
    await db.init_db(settings.database.path)

    registered = await db.list_streamers(db_path=settings.database.path)
    approved = [s for s in registered if s["approved"]]
    log.info(
        "Banco de dados: %d streamers registrados, %d aprovados",
        len(registered), len(approved),
    )

    yield


app = FastAPI(
    title="RatoNet Dashboard",
    description="Plataforma open-source para streaming IRL de alta estabilidade",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS para desenvolvimento
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rotas
app.include_router(router)
app.include_router(admin_router)


# --- WebSocket endpoints ---

@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    """WebSocket para browsers (recebe atualizações de telemetria)."""
    await manager.connect_dashboard(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_dashboard(ws)


@app.websocket("/ws/field/{streamer_id}")
async def ws_field(ws: WebSocket, streamer_id: str, key: str = Query(default="")):
    """WebSocket para field agents (autenticado por API key)."""
    # Valida API key
    if not key:
        await ws.close(code=4001, reason="API key obrigatória: ?key=SUA_KEY")
        return

    streamer_data = await db.get_streamer_by_api_key(key, db_path=settings.database.path)
    if not streamer_data:
        await ws.close(code=4001, reason="API key inválida")
        return

    if streamer_data["id"] != streamer_id:
        await ws.close(code=4001, reason="API key não corresponde ao streamer_id")
        return

    if not streamer_data["approved"]:
        await ws.close(code=4003, reason="Streamer não aprovado. Aguarde aprovação do admin.")
        return

    # Conecta
    await manager.connect_field(ws, streamer_id, streamer_data)
    try:
        while True:
            data = await ws.receive_text()
            await manager.handle_field_message(streamer_id, data)
    except WebSocketDisconnect:
        manager.disconnect_field(streamer_id)


# --- Serve frontend estático ---

@app.get("/")
async def serve_index():
    """Serve o dashboard frontend."""
    index_path = STATIC_DIR / "index.html"
    return FileResponse(index_path)


@app.get("/panel")
@app.get("/panel/")
async def serve_panel():
    """Serve o painel do streamer."""
    panel_index = STATIC_DIR / "static" / "panel" / "index.html"
    if panel_index.exists():
        return FileResponse(panel_index)
    return {"error": "Panel not found"}


@app.get("/admin")
@app.get("/admin/")
async def serve_admin_panel():
    """Serve o painel de administração."""
    admin_index = STATIC_DIR / "static" / "admin" / "index.html"
    if admin_index.exists():
        return FileResponse(admin_index)
    return {"error": "Admin panel not found"}


@app.get("/pwa")
@app.get("/pwa/")
async def serve_pwa_index():
    """Serve a PWA GPS Tracker."""
    pwa_index = STATIC_DIR / "static" / "pwa" / "index.html"
    if pwa_index.exists():
        return FileResponse(pwa_index)
    return {"error": "PWA not found"}


@app.get("/pwa/{path:path}")
async def serve_pwa_file(path: str):
    """Serve arquivos da PWA."""
    file_path = STATIC_DIR / "static" / "pwa" / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    # SPA fallback — retorna index.html para rotas do frontend
    pwa_index = STATIC_DIR / "static" / "pwa" / "index.html"
    if pwa_index.exists():
        return FileResponse(pwa_index)
    return {"error": "Not found"}


if (STATIC_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR / "static"), name="static")


def main():
    """Entry point para rodar via `python -m ratonet.dashboard.main`."""
    import uvicorn

    log.info("Iniciando RatoNet Dashboard em %s:%d", settings.dashboard.host, settings.dashboard.port)
    uvicorn.run(
        "ratonet.dashboard.main:app",
        host=settings.dashboard.host,
        port=settings.dashboard.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
