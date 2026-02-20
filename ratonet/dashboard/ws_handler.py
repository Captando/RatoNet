"""WebSocket handlers para comunicação em tempo real.

Dois endpoints:
- /ws/field   → recebe telemetria dos field agents
- /ws/dashboard → envia atualizações para os browsers
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone

from typing import Dict, List

from fastapi import WebSocket, WebSocketDisconnect

from ratonet.common.logger import get_logger
from ratonet.common.protocol import MessageType, ProtocolMessage
from ratonet.dashboard.models import (
    DashboardUpdate,
    GPSPosition,
    HardwareMetrics,
    HealthState,
    HealthStatus,
    NetworkLink,
    StarlinkMetrics,
    Streamer,
)

log = get_logger("ws")


class ConnectionManager:
    """Gerencia conexões WebSocket de browsers e field agents."""

    def __init__(self) -> None:
        self.dashboard_clients: List[WebSocket] = []
        self.field_agents: Dict[str, WebSocket] = {}  # streamer_id → ws
        self.streamers: Dict[str, Streamer] = {}

    # --- Dashboard (browsers) ---

    async def connect_dashboard(self, ws: WebSocket) -> None:
        await ws.accept()
        self.dashboard_clients.append(ws)
        log.info("Dashboard conectado. Total: %d", len(self.dashboard_clients))
        # Envia estado atual completo
        await self._send_full_sync(ws)

    def disconnect_dashboard(self, ws: WebSocket) -> None:
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
            self.dashboard_clients.remove(client)

    async def _send_full_sync(self, ws: WebSocket) -> None:
        """Envia snapshot completo de todos os streamers."""
        streamers_data = [s.model_dump(mode="json") for s in self.streamers.values()]
        update = DashboardUpdate(type="full_sync", data={"streamers": streamers_data})
        await ws.send_text(update.model_dump_json())

    # --- Field agents ---

    async def connect_field(self, ws: WebSocket, streamer_id: str) -> None:
        await ws.accept()
        self.field_agents[streamer_id] = ws
        log.info("Field agent conectado: %s", streamer_id)

    def disconnect_field(self, streamer_id: str) -> None:
        self.field_agents.pop(streamer_id, None)
        if streamer_id in self.streamers:
            self.streamers[streamer_id].is_live = False
        log.info("Field agent desconectado: %s", streamer_id)

    async def handle_field_message(self, streamer_id: str, raw: str) -> None:
        """Processa mensagem de telemetria do field agent."""
        try:
            msg = ProtocolMessage.model_validate_json(raw)
        except Exception:
            log.warning("Mensagem inválida de %s: %s", streamer_id, raw[:100])
            return

        streamer = self.streamers.get(streamer_id)
        if not streamer:
            log.warning("Streamer desconhecido: %s", streamer_id)
            return

        streamer.updated_at = datetime.now(timezone.utc)

        if msg.type == MessageType.GPS:
            streamer.gps = GPSPosition(**msg.data)
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

    # --- Dados simulados (demo mode) ---

    def load_demo_streamers(self) -> None:
        """Carrega streamers de demonstração (mesmo do mock HTML)."""
        demo_data = [
            {"id": "1", "name": "Ricardo ACF", "color": "#f97316", "is_crown": True,
             "avatar_url": "https://helios.ratonet.com.br/api/v1/users/cml9nyu730002l1rgtvkt8j3i/avatar",
             "gps": {"lat": -4.2, "lng": -55.8, "speed_kmh": 0}},
            {"id": "2", "name": "Douglas Mesquita", "color": "#ec4899",
             "avatar_url": "https://helios.ratonet.com.br/api/v1/users/cml15dn9n000011u4n2d28d9w/avatar",
             "socials": ["instagram", "tiktok", "twitter", "youtube"],
             "gps": {"lat": -4.3, "lng": -56.0, "speed_kmh": 11}},
            {"id": "3", "name": "Guilherme Tonimek", "color": "#3b82f6",
             "avatar_url": "https://helios.ratonet.com.br/api/v1/users/cmlhvr4by00w7hchbnauo56w9/avatar",
             "gps": {"lat": -4.4, "lng": -56.2, "speed_kmh": 12}},
            {"id": "4", "name": "Willian Gordox", "color": "#a855f7",
             "avatar_url": "https://helios.ratonet.com.br/api/v1/users/cmljanpob008010dxlpec5h0g/avatar",
             "gps": {"lat": -4.5, "lng": -55.5, "speed_kmh": 70}},
            {"id": "5", "name": "Richard Rasmussen", "color": "#10b981",
             "avatar_url": "https://helios.ratonet.com.br/api/v1/users/cmlgm0t5y00k5r75t0x47q6w6/avatar",
             "gps": {"lat": -4.7, "lng": -56.1, "speed_kmh": 0}},
            {"id": "6", "name": "Julio Balestrin", "color": "#ef4444",
             "avatar_url": "https://helios.ratonet.com.br/api/v1/users/cmlrtqxlx2fwsec7havmx7v6d/avatar",
             "gps": {"lat": -4.6, "lng": -55.2, "speed_kmh": 0}},
        ]

        for d in demo_data:
            gps_data = d.pop("gps", {})
            streamer = Streamer(**d, gps=GPSPosition(**gps_data), is_live=True)
            streamer.health = HealthStatus(
                score=random.randint(60, 100),
                state=HealthState.HEALTHY,
                active_links=random.randint(1, 3),
                total_links=3,
                bitrate_kbps=random.uniform(3000, 6000),
            )
            streamer.hardware = HardwareMetrics(
                cpu_percent=random.uniform(20, 60),
                cpu_temp_c=random.uniform(45, 65),
                ram_percent=random.uniform(30, 70),
                battery_percent=random.uniform(40, 100),
            )
            self.streamers[d["id"]] = streamer

    async def run_demo_simulation(self) -> None:
        """Simula atualizações de telemetria em modo demo."""
        log.info("Modo demo ativo - simulando telemetria")
        while True:
            await asyncio.sleep(2)
            for streamer in self.streamers.values():
                # Simula pequenas variações de posição
                streamer.gps.lat += random.uniform(-0.001, 0.001)
                streamer.gps.lng += random.uniform(-0.001, 0.001)
                streamer.gps.speed_kmh = max(0, streamer.gps.speed_kmh + random.uniform(-5, 5))

                # Simula variações de hardware
                streamer.hardware.cpu_percent = max(5, min(95, streamer.hardware.cpu_percent + random.uniform(-3, 3)))
                streamer.hardware.cpu_temp_c = max(35, min(80, streamer.hardware.cpu_temp_c + random.uniform(-1, 1)))

                # Simula variações de saúde
                streamer.health.score = max(20, min(100, streamer.health.score + random.randint(-5, 5)))
                if streamer.health.score >= 70:
                    streamer.health.state = HealthState.HEALTHY
                elif streamer.health.score >= 40:
                    streamer.health.state = HealthState.DEGRADED
                else:
                    streamer.health.state = HealthState.CRITICAL

                streamer.updated_at = datetime.now(timezone.utc)

            # Broadcast para dashboards conectados
            if self.dashboard_clients:
                streamers_data = [s.model_dump(mode="json") for s in self.streamers.values()]
                update = DashboardUpdate(type="full_sync", data={"streamers": streamers_data})
                await self.broadcast_to_dashboards(update)


# Instância global
manager = ConnectionManager()
