"""Modelos Pydantic para o dashboard e API."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Dict, List, Optional
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, Field


def validate_avatar(value: str) -> str:
    if value and (urlsplit(value).scheme not in ("http", "https") or not urlsplit(value).hostname):
        raise ValueError("Avatar deve ser uma URL HTTP(S)")
    return value


AvatarURL = Annotated[str, Field(max_length=2048), AfterValidator(validate_avatar)]
ProfileName = Annotated[str, Field(min_length=1, max_length=100)]
ProfileColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


def validate_rtmp_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in ("rtmp", "rtmps") or not parsed.hostname:
        raise ValueError("Destino deve ser uma URL RTMP(S)")
    # FFmpeg tee has its own separators, independent of shell escaping.
    if any(c in value for c in "|[]\\'\n\r\x00") or any(ord(c) < 32 for c in value):
        raise ValueError("Caracteres inválidos na URL RTMP")
    return value


# --- GPS ---

class GPSPosition(BaseModel):
    lat: float = Field(default=0.0, ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(default=0.0, ge=-180, le=180, allow_inf_nan=False)
    speed_kmh: float = 0.0
    altitude_m: float = 0.0
    heading: float = 0.0
    satellites: int = 0
    fix: str = "none"  # none, 2d, 3d


# --- Hardware ---

class HardwareMetrics(BaseModel):
    cpu_percent: float = 0.0
    cpu_temp_c: float = 0.0
    ram_percent: float = 0.0
    disk_percent: float = 0.0
    battery_percent: Optional[float] = None
    battery_charging: bool = False


# --- Rede ---

class NetworkLink(BaseModel):
    interface: str
    type: str = "unknown"  # 4g, wifi, starlink, ethernet
    connected: bool = False
    rtt_ms: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_pct: float = 0.0
    bandwidth_mbps: float = 0.0
    score: int = 0  # 0-100


# --- Starlink ---

class StarlinkMetrics(BaseModel):
    connected: bool = False
    latency_ms: float = 0.0
    download_mbps: float = 0.0
    upload_mbps: float = 0.0
    obstruction_pct: float = 0.0
    uptime_s: int = 0


# --- Saúde ---

class HealthState(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    DOWN = "down"


class HealthStatus(BaseModel):
    score: int = Field(default=0, ge=0, le=100)
    state: HealthState = HealthState.UNKNOWN
    active_links: int = 0
    total_links: int = 0
    bitrate_kbps: float = 0.0
    message: str = "Sem dados de vídeo"


# --- Stream Destinations ---

class StreamDestination(BaseModel):
    """Destino RTMP para relay (Twitch, YouTube, Kick, etc.)."""
    platform: str = Field(pattern=r"^(twitch|youtube|kick|custom)$")
    rtmp_url: Annotated[str, Field(max_length=2048), AfterValidator(validate_rtmp_url)]
    enabled: bool = True


# --- Streamer ---

class Streamer(BaseModel):
    id: str
    name: str
    avatar_url: str = ""
    color: str = "#ff6600"
    is_crown: bool = False
    is_live: bool = False
    socials: List[str] = Field(default_factory=list)
    stream_destinations: List[StreamDestination] = Field(default_factory=list)

    gps: GPSPosition = Field(default_factory=GPSPosition)
    hardware: HardwareMetrics = Field(default_factory=HardwareMetrics)
    network_links: List[NetworkLink] = Field(default_factory=list)
    starlink: StarlinkMetrics = Field(default_factory=StarlinkMetrics)
    health: HealthStatus = Field(default_factory=HealthStatus)
    location_name: str = ""

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- WebSocket messages para o frontend ---

class DashboardUpdate(BaseModel):
    """Mensagem enviada ao frontend via WebSocket."""
    type: str  # "streamer_update", "health_update", "full_sync"
    data: dict


# --- Registro / API ---

class RegisterRequest(BaseModel):
    """Request de cadastro de novo streamer."""
    name: ProfileName
    email: str = Field(min_length=3, max_length=254)
    avatar_url: AvatarURL = ""
    color: ProfileColor = "#ff6600"
    socials: List[str] = Field(default_factory=list)


class RegisterResponse(BaseModel):
    """Response do cadastro com credenciais."""
    id: str
    name: str
    api_key: str
    pull_key: str = ""
    approved: bool
    server_url: str = ""
    message: str = ""


class ProfileUpdate(BaseModel):
    """Request de atualização de perfil."""
    name: Optional[ProfileName] = None
    avatar_url: Optional[AvatarURL] = None
    color: Optional[ProfileColor] = None
    socials: Optional[List[str]] = None


class StreamerPublic(BaseModel):
    """Dados públicos do streamer (sem api_key)."""
    id: str
    name: str
    avatar_url: str = ""
    color: str = "#ff6600"
    is_crown: bool = False
    is_live: bool = False
    socials: List[str] = Field(default_factory=list)
    approved: bool = False

    gps: GPSPosition = Field(default_factory=GPSPosition)
    hardware: HardwareMetrics = Field(default_factory=HardwareMetrics)
    network_links: List[NetworkLink] = Field(default_factory=list)
    starlink: StarlinkMetrics = Field(default_factory=StarlinkMetrics)
    health: HealthStatus = Field(default_factory=HealthStatus)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
