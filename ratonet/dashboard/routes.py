"""REST endpoints do dashboard."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ratonet.common.logger import get_logger
from ratonet.dashboard.ws_handler import manager

log = get_logger("routes")
router = APIRouter(prefix="/api")


@router.get("/streamers")
async def get_streamers():
    """Retorna lista de streamers ativos com dados atuais."""
    return [s.model_dump(mode="json") for s in manager.streamers.values()]


@router.get("/streamers/{streamer_id}")
async def get_streamer(streamer_id: str):
    """Retorna dados de um streamer específico."""
    streamer = manager.streamers.get(streamer_id)
    if not streamer:
        return {"error": "Streamer não encontrado"}, 404
    return streamer.model_dump(mode="json")


@router.get("/health")
async def get_health():
    """Retorna health status de todos os streamers."""
    return {
        sid: {"name": s.name, "health": s.health.model_dump(mode="json")}
        for sid, s in manager.streamers.items()
    }


@router.get("/status")
async def get_status():
    """Status geral do sistema."""
    return {
        "streamers_online": sum(1 for s in manager.streamers.values() if s.is_live),
        "streamers_total": len(manager.streamers),
        "dashboard_clients": len(manager.dashboard_clients),
        "field_agents": len(manager.field_agents),
    }
