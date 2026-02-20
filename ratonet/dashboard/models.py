"""Modelos Pydantic para o dashboard e API."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# --- GPS ---

class GPSPosition(BaseModel):
    lat: float
    lng: float
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
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    DOWN = "down"


class HealthStatus(BaseModel):
    score: int = 100  # 0-100
    state: HealthState = HealthState.HEALTHY
    active_links: int = 0
    total_links: int = 0
    bitrate_kbps: float = 0.0
    message: str = ""


# --- Streamer ---

class Streamer(BaseModel):
    id: str
    name: str
    avatar_url: str = ""
    color: str = "#ff6600"
    is_crown: bool = False
    is_live: bool = False
    socials: List[str] = Field(default_factory=list)

    gps: GPSPosition = Field(default_factory=GPSPosition)
    hardware: HardwareMetrics = Field(default_factory=HardwareMetrics)
    network_links: List[NetworkLink] = Field(default_factory=list)
    starlink: StarlinkMetrics = Field(default_factory=StarlinkMetrics)
    health: HealthStatus = Field(default_factory=HealthStatus)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- WebSocket messages para o frontend ---

class DashboardUpdate(BaseModel):
    """Mensagem enviada ao frontend via WebSocket."""
    type: str  # "streamer_update", "health_update", "full_sync"
    data: dict


# --- Registro / API ---

class RegisterRequest(BaseModel):
    """Request de cadastro de novo streamer."""
    name: str
    email: str
    avatar_url: str = ""
    color: str = "#ff6600"
    socials: List[str] = Field(default_factory=list)


class RegisterResponse(BaseModel):
    """Response do cadastro com credenciais."""
    id: str
    name: str
    api_key: str
    approved: bool
    server_url: str = ""
    message: str = ""


class ProfileUpdate(BaseModel):
    """Request de atualização de perfil."""
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    color: Optional[str] = None
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
