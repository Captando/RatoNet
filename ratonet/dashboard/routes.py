"""REST endpoints do dashboard — registro, perfil, streamers, saúde."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Query

from ratonet.common.logger import get_logger
from ratonet.config import settings
from ratonet.dashboard import db
from datetime import datetime, timezone

from pydantic import BaseModel

from ratonet.dashboard.geocoder import get_cached_location
from ratonet.dashboard.models import DashboardUpdate, GPSPosition, ProfileUpdate, RegisterRequest, RegisterResponse, StreamDestination
from ratonet.dashboard.ws_handler import manager

log = get_logger("routes")
router = APIRouter(prefix="/api")


# --- Registro ---

@router.post("/register", response_model=RegisterResponse)
async def register_streamer(req: RegisterRequest):
    """Cadastra novo streamer na plataforma."""
    existing = await db.get_streamer_by_email(req.email, db_path=settings.database.path)
    if existing:
        raise HTTPException(status_code=409, detail="Email já cadastrado")

    result = await db.create_streamer(
        name=req.name,
        email=req.email,
        avatar_url=req.avatar_url,
        color=req.color,
        socials=req.socials,
        auto_approve=settings.database.auto_approve,
        db_path=settings.database.path,
    )

    msg = "Cadastro realizado! Aguardando aprovação do admin."
    if settings.database.auto_approve:
        msg = "Cadastro aprovado automaticamente. Configure seu field agent."

    return RegisterResponse(
        id=result["id"],
        name=result["name"],
        api_key=result["api_key"],
        pull_key=result.get("pull_key", ""),
        approved=result["approved"],
        server_url=settings.field.server_ws_url,
        message=msg,
    )


# --- Perfil do Streamer (autenticado por api_key) ---

async def _get_current_streamer(api_key: str):
    """Autentica streamer pela API key."""
    if not api_key:
        raise HTTPException(status_code=401, detail="API key obrigatória")
    streamer = await db.get_streamer_by_api_key(api_key, db_path=settings.database.path)
    if not streamer:
        raise HTTPException(status_code=401, detail="API key inválida")
    return streamer


@router.get("/me")
async def get_my_profile(api_key: str = Query(..., description="Sua API key")):
    """Retorna dados do próprio streamer."""
    streamer = await _get_current_streamer(api_key)
    safe = {k: v for k, v in streamer.items() if k != "api_key"}
    live = manager.streamers.get(streamer["id"])
    if live:
        safe["is_live"] = True
        safe["gps"] = live.gps.model_dump()
        safe["hardware"] = live.hardware.model_dump()
        safe["health"] = live.health.model_dump()
    else:
        safe["is_live"] = False
    return safe


@router.put("/me")
async def update_my_profile(
    update: ProfileUpdate,
    api_key: str = Query(..., description="Sua API key"),
):
    """Atualiza perfil do streamer."""
    streamer = await _get_current_streamer(api_key)
    updates = update.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    await db.update_streamer(streamer["id"], db_path=settings.database.path, **updates)
    return {"message": "Perfil atualizado", "updated": list(updates.keys())}


@router.get("/me/config")
async def get_my_field_config(api_key: str = Query(..., description="Sua API key")):
    """Retorna configuração pronta para o field agent."""
    streamer = await _get_current_streamer(api_key)
    return {
        "streamer_id": streamer["id"],
        "server_ws_url": settings.field.server_ws_url,
        "api_key": api_key,
        "env_content": (
            f"FIELD_SERVER_WS_URL={settings.field.server_ws_url}\n"
            f"FIELD_STREAMER_ID={streamer['id']}\n"
            f"FIELD_API_KEY={api_key}\n"
            f"FIELD_TELEMETRY_INTERVAL_S=1.0\n"
            f"FIELD_GPS_DEVICE=localhost:2947\n"
            f"FIELD_STARLINK_ADDR=192.168.100.1:9200\n"
        ),
    }


# --- Stream Destinations ---

def _mask_rtmp_url(url: str) -> str:
    """Mascara a stream key na URL RTMP."""
    parts = url.rsplit("/", 1)
    if len(parts) == 2 and len(parts[1]) > 4:
        return parts[0] + "/" + parts[1][:4] + "***"
    return url


@router.get("/me/destinations")
async def get_my_destinations(api_key: str = Query(..., description="Sua API key")):
    """Lista destinos de stream configurados."""
    streamer = await _get_current_streamer(api_key)
    config = streamer.get("config", {})
    destinations = config.get("stream_destinations", [])
    # Mascara as URLs RTMP
    masked = []
    for dest in destinations:
        masked.append({
            "platform": dest.get("platform", "custom"),
            "rtmp_url": _mask_rtmp_url(dest.get("rtmp_url", "")),
            "enabled": dest.get("enabled", True),
        })
    return {"destinations": masked}


@router.put("/me/destinations")
async def update_my_destinations(
    destinations: List[StreamDestination],
    api_key: str = Query(..., description="Sua API key"),
):
    """Atualiza lista de destinos de stream (Twitch, YouTube, etc.)."""
    streamer = await _get_current_streamer(api_key)
    config = streamer.get("config", {})
    config["stream_destinations"] = [d.model_dump() for d in destinations]
    await db.update_streamer(streamer["id"], db_path=settings.database.path, config=config)
    log.info("Destinations atualizados para %s: %d destinos", streamer["name"], len(destinations))
    return {"message": "Destinos atualizados", "count": len(destinations)}


@router.get("/me/destinations/full")
async def get_my_destinations_full(api_key: str = Query(..., description="Sua API key")):
    """Lista destinos de stream SEM mascarar (para o painel do streamer editar)."""
    streamer = await _get_current_streamer(api_key)
    config = streamer.get("config", {})
    destinations = config.get("stream_destinations", [])
    return {"destinations": destinations}


# --- LivePix ---

class LivePixToken(BaseModel):
    token: str


@router.get("/me/livepix")
async def get_my_livepix(api_key: str = Query(..., description="Sua API key")):
    """Retorna token LivePix configurado."""
    streamer = await _get_current_streamer(api_key)
    config = streamer.get("config", {})
    return {"token": config.get("livepix_token", "")}


@router.put("/me/livepix")
async def update_my_livepix(
    data: LivePixToken,
    api_key: str = Query(..., description="Sua API key"),
):
    """Salva token LivePix no config."""
    streamer = await _get_current_streamer(api_key)
    config = streamer.get("config", {})
    config["livepix_token"] = data.token
    await db.update_streamer(streamer["id"], db_path=settings.database.path, config=config)
    return {"message": "Token LivePix salvo"}


# --- Streamers públicos ---

@router.get("/streamers")
async def get_streamers():
    """Retorna streamers aprovados com dados de telemetria ao vivo."""
    db_streamers = await db.list_streamers(approved_only=True, db_path=settings.database.path)

    result = []
    for s in db_streamers:
        entry = {
            "id": s["id"],
            "name": s["name"],
            "avatar_url": s["avatar_url"],
            "color": s["color"],
            "is_crown": s["is_crown"],
            "socials": s["socials"],
        }
        live = manager.streamers.get(s["id"])
        if live:
            entry["is_live"] = True
            entry["gps"] = live.gps.model_dump()
            entry["hardware"] = live.hardware.model_dump()
            entry["network_links"] = [nl.model_dump() for nl in live.network_links]
            entry["starlink"] = live.starlink.model_dump()
            entry["health"] = live.health.model_dump()
            entry["updated_at"] = live.updated_at.isoformat()
        else:
            entry["is_live"] = False
        result.append(entry)

    return result


@router.get("/streamers/{streamer_id}")
async def get_streamer(streamer_id: str):
    """Retorna dados de um streamer específico."""
    s = await db.get_streamer_by_id(streamer_id, db_path=settings.database.path)
    if not s:
        raise HTTPException(status_code=404, detail="Streamer não encontrado")
    if not s["approved"]:
        raise HTTPException(status_code=403, detail="Streamer não aprovado")

    result = {k: v for k, v in s.items() if k != "api_key"}
    live = manager.streamers.get(streamer_id)
    if live:
        result["is_live"] = True
        result["gps"] = live.gps.model_dump()
    else:
        result["is_live"] = False
    return result


# --- Overlay data (autenticado por pull_key) ---

@router.get("/overlay/data/{streamer_id}")
async def get_overlay_data(
    streamer_id: str,
    pull_key: str = Query(..., description="Pull key (read-only) do streamer"),
):
    """Retorna dados para overlays OBS (GPS, health, rede, localização)."""
    streamer_db = await db.get_streamer_by_pull_key(pull_key, db_path=settings.database.path)
    if not streamer_db or streamer_db["id"] != streamer_id:
        raise HTTPException(status_code=401, detail="Pull key inválida")

    config = streamer_db.get("config", {})
    livepix_token = config.get("livepix_token", "")

    live = manager.streamers.get(streamer_id)
    if not live:
        return {
            "is_live": False,
            "streamer_id": streamer_id,
            "name": streamer_db["name"],
            "livepix_token": livepix_token,
        }

    return {
        "is_live": True,
        "streamer_id": streamer_id,
        "name": streamer_db["name"],
        "gps": live.gps.model_dump(),
        "hardware": live.hardware.model_dump(),
        "network_links": [nl.model_dump() for nl in live.network_links],
        "starlink": live.starlink.model_dump(),
        "health": live.health.model_dump(),
        "location_name": get_cached_location(streamer_id) or "",
        "livepix_token": livepix_token,
        "updated_at": live.updated_at.isoformat(),
    }


# --- Location push (REST fallback para PWA) ---

class LocationPush(BaseModel):
    lat: float
    lng: float
    speed_kmh: float = 0.0
    altitude_m: float = 0.0
    heading: float = 0.0
    accuracy_m: float = 0.0


@router.post("/location")
async def push_location(
    location: LocationPush,
    streamer_id: str = Query(...),
    api_key: str = Query(...),
):
    """Push GPS via REST (fallback para quando WebSocket não está disponível)."""
    streamer_db = await db.get_streamer_by_api_key(api_key, db_path=settings.database.path)
    if not streamer_db or streamer_db["id"] != streamer_id:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    live = manager.streamers.get(streamer_id)
    if not live:
        # Cria streamer ao vivo temporário (PWA pode ser a única fonte)
        from ratonet.dashboard.models import Streamer
        live = Streamer(
            id=streamer_db["id"],
            name=streamer_db["name"],
            avatar_url=streamer_db.get("avatar_url", ""),
            color=streamer_db.get("color", "#ff6600"),
            is_crown=streamer_db.get("is_crown", False),
            socials=streamer_db.get("socials", []),
            is_live=True,
        )
        manager.streamers[streamer_id] = live
        # Notifica dashboards
        update = DashboardUpdate(
            type="streamer_online",
            data={"streamer": live.model_dump(mode="json")},
        )
        await manager.broadcast_to_dashboards(update)

    live.gps = GPSPosition(
        lat=location.lat,
        lng=location.lng,
        speed_kmh=location.speed_kmh,
        altitude_m=location.altitude_m,
        heading=location.heading,
    )
    live.updated_at = datetime.now(timezone.utc)

    # Broadcast para dashboards
    update = DashboardUpdate(
        type="streamer_update",
        data={"streamer_id": streamer_id, "streamer": live.model_dump(mode="json")},
    )
    await manager.broadcast_to_dashboards(update)

    return {"message": "Localização atualizada", "lat": location.lat, "lng": location.lng}


@router.get("/health")
async def get_health():
    """Retorna health status de streamers ao vivo."""
    return {
        sid: {"name": s.name, "health": s.health.model_dump(mode="json")}
        for sid, s in manager.streamers.items()
    }


@router.get("/status")
async def get_status():
    """Status geral do sistema."""
    total_registered = len(await db.list_streamers(db_path=settings.database.path))
    total_approved = len(await db.list_streamers(approved_only=True, db_path=settings.database.path))
    return {
        "streamers_registered": total_registered,
        "streamers_approved": total_approved,
        "streamers_online": len(manager.streamers),
        "dashboard_clients": len(manager.dashboard_clients),
        "field_agents": len(manager.field_agents),
    }
