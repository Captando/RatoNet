"""Endpoints de administração — gerenciar streamers, aprovações."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header

from ratonet.common.logger import get_logger
from ratonet.config import settings
from ratonet.dashboard import db
from ratonet.dashboard.ws_handler import manager

log = get_logger("admin")
admin_router = APIRouter(prefix="/api/admin")


def _verify_admin_token(authorization: str = Header(default="")):
    """Verifica token de admin no header Authorization."""
    token = settings.admin.token
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Admin não configurado. Defina ADMIN_TOKEN no .env",
        )
    # Aceita "Bearer <token>" ou token direto
    provided = authorization.replace("Bearer ", "").strip()
    if provided != token:
        raise HTTPException(status_code=401, detail="Token de admin inválido")


@admin_router.get("/streamers")
async def list_all_streamers(admin: None = Depends(_verify_admin_token)):
    """Lista todos os streamers (incluindo pendentes)."""
    all_streamers = await db.list_streamers(approved_only=False, db_path=settings.database.path)

    result = []
    for s in all_streamers:
        entry = {k: v for k, v in s.items() if k != "api_key"}
        live = manager.streamers.get(s["id"])
        entry["is_live"] = live is not None
        result.append(entry)

    return result


@admin_router.post("/streamers/{streamer_id}/approve")
async def approve_streamer(
    streamer_id: str,
    admin: None = Depends(_verify_admin_token),
):
    """Aprova um streamer pendente."""
    streamer = await db.get_streamer_by_id(streamer_id, db_path=settings.database.path)
    if not streamer:
        raise HTTPException(status_code=404, detail="Streamer não encontrado")
    if streamer["approved"]:
        return {"message": "Streamer já está aprovado", "id": streamer_id}

    await db.approve_streamer(streamer_id, db_path=settings.database.path)
    log.info("Streamer aprovado: %s (%s)", streamer["name"], streamer_id)
    return {"message": "Streamer aprovado", "id": streamer_id, "name": streamer["name"]}


@admin_router.post("/streamers/{streamer_id}/crown")
async def toggle_crown(
    streamer_id: str,
    admin: None = Depends(_verify_admin_token),
):
    """Marca/desmarca streamer como host (crown)."""
    streamer = await db.get_streamer_by_id(streamer_id, db_path=settings.database.path)
    if not streamer:
        raise HTTPException(status_code=404, detail="Streamer não encontrado")

    new_crown = not streamer["is_crown"]
    await db.update_streamer(streamer_id, db_path=settings.database.path, is_crown=new_crown)
    return {"message": f"Crown {'ativado' if new_crown else 'desativado'}", "is_crown": new_crown}


@admin_router.delete("/streamers/{streamer_id}")
async def remove_streamer(
    streamer_id: str,
    admin: None = Depends(_verify_admin_token),
):
    """Remove streamer da plataforma."""
    streamer = await db.get_streamer_by_id(streamer_id, db_path=settings.database.path)
    if not streamer:
        raise HTTPException(status_code=404, detail="Streamer não encontrado")

    # Desconecta field agent se estiver online
    if streamer_id in manager.field_agents:
        ws = manager.field_agents[streamer_id]
        await ws.close(code=1008, reason="Removido pelo admin")
        manager.disconnect_field(streamer_id)

    # Remove do mapa ao vivo
    manager.streamers.pop(streamer_id, None)

    await db.delete_streamer(streamer_id, db_path=settings.database.path)
    log.info("Streamer removido: %s (%s)", streamer["name"], streamer_id)
    return {"message": "Streamer removido", "name": streamer["name"]}
