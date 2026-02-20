"""Configuração centralizada do RatoNet via variáveis de ambiente."""

from __future__ import annotations

from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings


class SRTConfig(BaseSettings):
    """Configuração do pipeline SRT."""

    model_config = {"env_prefix": "SRT_"}

    base_port: int = Field(default=9000, description="Porta base SRT (incrementa por link)")
    latency_ms: int = Field(default=500, description="Latência SRT em milissegundos")
    max_links: int = Field(default=4, description="Máximo de links simultâneos")
    passphrase: str = Field(default="", description="Passphrase SRT (vazio = sem criptografia)")


class RTMPConfig(BaseSettings):
    """Destinos RTMP para relay."""

    model_config = {"env_prefix": "RTMP_"}

    primary_url: str = Field(default="", description="URL RTMP primária (ex: rtmp://live.twitch.tv/app/KEY)")
    secondary_url: str = Field(default="", description="URL RTMP secundária (ex: YouTube)")


class OBSConfig(BaseSettings):
    """Configuração do OBS WebSocket."""

    model_config = {"env_prefix": "OBS_"}

    host: str = Field(default="localhost", description="Host do OBS WebSocket")
    port: int = Field(default=4455, description="Porta do OBS WebSocket")
    password: str = Field(default="", description="Senha do OBS WebSocket")
    scene_live: str = Field(default="LIVE", description="Nome da cena ao vivo")
    scene_brb: str = Field(default="BRB", description="Nome da cena de fallback")
    fallback_delay_s: float = Field(default=3.0, description="Delay antes de acionar fallback (segundos)")
    recovery_delay_s: float = Field(default=5.0, description="Delay antes de restaurar cena ao vivo")


class FieldConfig(BaseSettings):
    """Configuração do agente de campo."""

    model_config = {"env_prefix": "FIELD_"}

    server_ws_url: str = Field(default="ws://localhost:8000/ws/field", description="URL WebSocket do servidor")
    telemetry_interval_s: float = Field(default=1.0, description="Intervalo de envio de telemetria (segundos)")
    gps_device: str = Field(default="localhost:2947", description="Endereço do gpsd (host:port)")
    starlink_addr: str = Field(default="192.168.100.1:9200", description="Endereço gRPC do Starlink dish")
    network_interfaces: List[str] = Field(default_factory=list, description="Interfaces de rede para bonding")
    video_device: str = Field(default="/dev/video0", description="Dispositivo de captura de vídeo")
    video_bitrate: str = Field(default="4000k", description="Bitrate do vídeo")
    video_resolution: str = Field(default="1920x1080", description="Resolução do vídeo")
    video_codec: str = Field(default="libx264", description="Codec de vídeo")


class HealthConfig(BaseSettings):
    """Thresholds do monitor de saúde."""

    model_config = {"env_prefix": "HEALTH_"}

    threshold_degraded: int = Field(default=70, description="Score abaixo = DEGRADED")
    threshold_critical: int = Field(default=40, description="Score abaixo = CRITICAL")
    threshold_down: int = Field(default=10, description="Score abaixo = DOWN")
    check_interval_s: float = Field(default=2.0, description="Intervalo de checagem (segundos)")


class DatabaseConfig(BaseSettings):
    """Configuração do banco de dados."""

    model_config = {"env_prefix": "DB_"}

    path: str = Field(default="ratonet.db", description="Caminho do arquivo SQLite")
    auto_approve: bool = Field(default=False, description="Aprovar streamers automaticamente no cadastro")


class AdminConfig(BaseSettings):
    """Configuração de administração."""

    model_config = {"env_prefix": "ADMIN_"}

    token: str = Field(default="", description="Token de autenticação do admin (obrigatório em produção)")


class DashboardConfig(BaseSettings):
    """Configuração do dashboard/API."""

    model_config = {"env_prefix": "DASHBOARD_"}

    host: str = Field(default="0.0.0.0", description="Host do servidor")
    port: int = Field(default=8000, description="Porta do servidor")
    static_dir: str = Field(default=".", description="Diretório dos arquivos estáticos")


class Settings(BaseSettings):
    """Configuração raiz que agrega todas as sub-configurações."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    srt: SRTConfig = Field(default_factory=SRTConfig)
    rtmp: RTMPConfig = Field(default_factory=RTMPConfig)
    obs: OBSConfig = Field(default_factory=OBSConfig)
    field: FieldConfig = Field(default_factory=FieldConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)


settings = Settings()
