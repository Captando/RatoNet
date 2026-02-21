"""WebSocket handlers para comunicação em tempo real.

Endpoints:
- /ws/field/{streamer_id}?key=API_KEY → recebe telemetria dos field agents
- /ws/dashboard → envia atualizações para os browsers
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import WebSocket, WebSocketDisconnect

from ratonet.common.logger import get_logger
from ratonet.common.protocol import MessageType, ProtocolMessage
from ratonet.dashboard.geocoder import reverse_geocode
from ratonet.dashboard.models import (
    DashboardUpdate,
    GPSPosition,
    HardwareMetrics,
    HealthStatus,
    NetworkLink,
    StarlinkMetrics,
    Streamer,
)
from ratonet.server.relay import StreamerRelayManager
from ratonet.server.srt_receiver import PortAllocator

log = get_logger("ws")


class ConnectionManager:
    """Gerencia conexões WebSocket de browsers e field agents."""

    def __init__(self) -> None:
        self.dashboard_clients: List[WebSocket] = []
        self.field_agents: Dict[str, WebSocket] = {}  # streamer_id → ws
        self.streamers: Dict[str, Streamer] = {}  # streamers ao vivo (populado dinamicamente)
        self.streamer_relay: StreamerRelayManager = StreamerRelayManager()
        self.port_allocator: PortAllocator = PortAllocator()

    # --- Dashboard (browsers) ---

    async def connect_dashboard(self, ws: WebSocket) -> None:
        await ws.accept()
        self.dashboard_clients.append(ws)
        log.info("Dashboard conectado. Total: %d", len(self.dashboard_clients))
        await self._send_full_sync(ws)

    def disconnect_dashboard(self, ws: WebSocket) -> None:
        if ws in self.dashboard_clients:
            self.dashboard_clients.remove(ws)
        log.info("Dashboard desconectado. Total: %d", len(self.dashboard_clients))

    async def broadcast_to_dashboards(self, update: DashboardUpdate) -> None:
        """Envia atualização para todos os browsers conectados."""
        data = update.model_dump_json()
        disconnected = []
        for client in self.dashboard_clients:
            try:
                await client.send_text(data)
            except Exception:
                disconnected.append(client)
        for client in disconnected:
            if client in self.dashboard_clients:
                self.dashboard_clients.remove(client)

    async def _send_full_sync(self, ws: WebSocket) -> None:
        """Envia snapshot completo de todos os streamers ao vivo."""
        streamers_data = [s.model_dump(mode="json") for s in self.streamers.values()]
        update = DashboardUpdate(type="full_sync", data={"streamers": streamers_data})
        await ws.send_text(update.model_dump_json())

    # --- Field agents ---

    async def connect_field(self, ws: WebSocket, streamer_id: str, streamer_data: dict) -> None:
        """Conecta field agent e cria entrada de streamer ao vivo."""
        await ws.accept()
        self.field_agents[streamer_id] = ws

        # Cria streamer ao vivo a partir dos dados do DB
        self.streamers[streamer_id] = Streamer(
            id=streamer_data["id"],
            name=streamer_data["name"],
            avatar_url=streamer_data.get("avatar_url", ""),
            color=streamer_data.get("color", "#ff6600"),
            is_crown=streamer_data.get("is_crown", False),
            socials=streamer_data.get("socials", []),
            is_live=True,
        )

        log.info("Field agent conectado: %s (%s)", streamer_data["name"], streamer_id)

        # Sobe relay RTMP se tem destinos configurados
        config = streamer_data.get("config", {})
        destinations = config.get("stream_destinations", [])
        if destinations:
            srt_port = self.port_allocator.allocate(streamer_id)
            await self.streamer_relay.start_for_streamer(streamer_id, destinations, srt_port)

        # Notifica dashboards
        update = DashboardUpdate(
            type="streamer_online",
            data={"streamer": self.streamers[streamer_id].model_dump(mode="json")},
        )
        await self.broadcast_to_dashboards(update)

    def disconnect_field(self, streamer_id: str) -> None:
        """Desconecta field agent e remove streamer do mapa ao vivo."""
        self.field_agents.pop(streamer_id, None)
        removed = self.streamers.pop(streamer_id, None)
        name = removed.name if removed else streamer_id
        log.info("Field agent desconectado: %s (%s)", name, streamer_id)

        # Para relay RTMP do streamer
        asyncio.create_task(self.streamer_relay.stop_for_streamer(streamer_id))
        self.port_allocator.release(streamer_id)

        # Notifica dashboards
        update = DashboardUpdate(
            type="streamer_offline",
            data={"streamer_id": streamer_id},
        )
        # Fire and forget — não podemos await aqui (sync method)
        asyncio.create_task(self.broadcast_to_dashboards(update))

    async def handle_field_message(self, streamer_id: str, raw: str) -> None:
        """Processa mensagem de telemetria do field agent."""
        try:
            msg = ProtocolMessage.model_validate_json(raw)
        except Exception:
            log.warning("Mensagem inválida de %s: %s", streamer_id, raw[:100])
            return

        streamer = self.streamers.get(streamer_id)
        if not streamer:
            log.warning("Streamer não encontrado ao vivo: %s", streamer_id)
            return

        streamer.updated_at = datetime.now(timezone.utc)

        if msg.type == MessageType.GPS:
            streamer.gps = GPSPosition(**msg.data)
            # Reverse geocoding assíncrono (não bloqueia)
            asyncio.create_task(self._update_location(streamer_id, streamer.gps))
        elif msg.type == MessageType.HARDWARE:
            streamer.hardware = HardwareMetrics(**msg.data)
        elif msg.type == MessageType.NETWORK:
            streamer.network_links = [NetworkLink(**link) for link in msg.data.get("links", [])]
        elif msg.type == MessageType.STARLINK:
            streamer.starlink = StarlinkMetrics(**msg.data)
        elif msg.type == MessageType.HEALTH:
            streamer.health = HealthStatus(**msg.data)

        # Broadcast para dashboards
        update = DashboardUpdate(
            type="streamer_update",
            data={"streamer_id": streamer_id, "streamer": streamer.model_dump(mode="json")},
        )
        await self.broadcast_to_dashboards(update)


    async def _update_location(self, streamer_id: str, gps: GPSPosition) -> None:
        """Atualiza nome do local via reverse geocoding."""
        try:
            location = await reverse_geocode(streamer_id, gps.lat, gps.lng)
            streamer = self.streamers.get(streamer_id)
            if streamer and location:
                streamer.location_name = location
        except Exception:
            pass  # Silencioso — geocoding é best-effort


# Instância global
manager = ConnectionManager()
