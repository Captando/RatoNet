"""FastAPI application principal do RatoNet Dashboard."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ratonet.common.logger import get_logger
from ratonet.config import settings
from ratonet.dashboard.routes import router
from ratonet.dashboard.ws_handler import manager

log = get_logger("dashboard")

STATIC_DIR = Path(settings.dashboard.static_dir).resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown da aplicação."""
    # Carrega dados demo
    manager.load_demo_streamers()
    log.info("Carregados %d streamers demo", len(manager.streamers))

    # Inicia simulação demo em background
    demo_task = asyncio.create_task(manager.run_demo_simulation())

    yield

    # Cleanup
    demo_task.cancel()
    try:
        await demo_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="RatoNet Dashboard",
    description="Ecossistema open-source para streaming IRL de alta estabilidade",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS para desenvolvimento
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rotas REST
app.include_router(router)


# --- WebSocket endpoints ---

@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    """WebSocket para browsers (recebe atualizações de telemetria)."""
    await manager.connect_dashboard(ws)
    try:
        while True:
            # Mantém conexão aberta, aceita pings/mensagens do client
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_dashboard(ws)


@app.websocket("/ws/field/{streamer_id}")
async def ws_field(ws: WebSocket, streamer_id: str):
    """WebSocket para field agents (envia telemetria)."""
    await manager.connect_field(ws, streamer_id)
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


# Monta arquivos estáticos (CSS, JS, imagens futuras)
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
