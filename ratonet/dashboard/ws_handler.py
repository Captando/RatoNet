"""Telemetry sessions, media negotiation and dashboard broadcasts."""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import WebSocket
from pydantic import ValidationError

from ratonet.common.logger import get_logger
from ratonet.common.protocol import MessageType, ProtocolMessage
from ratonet.config import settings
from ratonet.dashboard.geocoder import reverse_geocode
from ratonet.dashboard.models import (
    DashboardUpdate, GPSPosition, HardwareMetrics, HealthStatus,
    NetworkLink, StarlinkMetrics, Streamer, HealthState,
)
from ratonet.server.relay import StreamerRelayManager
from ratonet.server.srt_receiver import PortAllocator, SRTLAReceiver

log = get_logger("ws")


class ConnectionManager:
    def __init__(self) -> None:
        self.dashboard_clients: List[WebSocket] = []
        self.field_agents: Dict[str, WebSocket] = {}
        self.gps_agents: Dict[str, WebSocket] = {}
        self.streamers: Dict[str, Streamer] = {}
        self.streamer_relay = StreamerRelayManager()
        self.port_allocator = PortAllocator(settings.srt.base_port, settings.srt.max_links,
                                            settings.srt.max_streamers)
        self.srtla_receivers: Dict[str, SRTLAReceiver] = {}
        self._lock = asyncio.Lock()
        self._geocoding: Dict[str, asyncio.Task] = {}
        self._gps_times: Dict[str, datetime] = {}
        self._gps_sources: Dict[str, str] = {}
        self._maintenance_task = None
        self._obs = None

    async def start(self) -> None:
        if settings.obs.streamer_id:
            from ratonet.server.obs_controller import OBSController
            self._obs = OBSController.from_config()
            await self._obs.connect()
        self._maintenance_task = asyncio.create_task(self._maintenance())

    async def stop(self) -> None:
        tasks = list(self._geocoding.values())
        if self._maintenance_task:
            tasks.append(self._maintenance_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.streamer_relay.stop_all()
        await asyncio.gather(*(r.stop() for r in self.srtla_receivers.values()))
        self.srtla_receivers.clear()
        if self._obs:
            self._obs.disconnect()
        self.field_agents.clear()
        self.gps_agents.clear()
        self.dashboard_clients.clear()
        self.streamers.clear()
        self.port_allocator.allocations.clear()
        self._gps_times.clear()
        self._gps_sources.clear()
        self._geocoding.clear()

    async def connect_dashboard(self, ws: WebSocket) -> None:
        await ws.accept()
        self.dashboard_clients.append(ws)
        update = DashboardUpdate(type="full_sync", data={
            "streamers": [s.model_dump(mode="json") for s in self.streamers.values()]})
        await ws.send_text(update.model_dump_json())

    def disconnect_dashboard(self, ws: WebSocket) -> None:
        if ws in self.dashboard_clients:
            self.dashboard_clients.remove(ws)

    async def broadcast_to_dashboards(self, update: DashboardUpdate) -> None:
        data = update.model_dump_json()

        async def send(client):
            try:
                await asyncio.wait_for(client.send_text(data), timeout=2)
            except Exception:
                self.disconnect_dashboard(client)

        await asyncio.gather(*(send(c) for c in list(self.dashboard_clients)))

    def ensure_streamer(self, data: dict) -> Streamer:
        sid = data["id"]
        if sid not in self.streamers:
            self.streamers[sid] = Streamer.model_validate({
                k: v for k, v in data.items() if k in (
                    "id", "name", "avatar_url", "color", "is_crown", "socials")
            })
            self.streamers[sid].is_live = True
        return self.streamers[sid]

    async def connect_field(self, ws: WebSocket, streamer_id: str, streamer_data: dict,
                            source: str = "field", video: bool = False,
                            transport: str = "srt") -> None:
        await ws.accept()
        async with self._lock:
            sessions = self.gps_agents if source == "gps" else self.field_agents
            previous = sessions.get(streamer_id)
            sessions[streamer_id] = ws
            if previous and previous is not ws:
                await previous.close(code=4000, reason="Sessão substituída")
            streamer = self.ensure_streamer(streamer_data)
            if source == "field":
                await self._stop_video(streamer_id)
                streamer.health = HealthStatus()
            config = None
            try:
                if source == "field" and video:
                    port = self.port_allocator.allocate(streamer_id)
                    passphrase = secrets.token_urlsafe(24)
                    use_srtla = False
                    if transport == "srtla" and settings.srtla.enabled:
                        receiver = SRTLAReceiver(port + 1, port, settings.srtla.binary_path)
                        use_srtla = await receiver.start()
                        if use_srtla:
                            self.srtla_receivers[streamer_id] = receiver
                    destinations = streamer_data.get("config", {}).get("stream_destinations", [])
                    await self.streamer_relay.start_for_streamer(
                        streamer_id, destinations, port, passphrase, localhost=use_srtla)
                    config = {"transport": "srtla" if use_srtla else "srt",
                              "port": port + 1 if use_srtla else port,
                              "passphrase": passphrase, "latency_ms": settings.srt.latency_ms}
                await ws.send_json({"type": "session_ready", "data": {"video": config}})
            except Exception:
                if source == "field":
                    await self._stop_video(streamer_id)
                sessions.pop(streamer_id, None)
                if streamer_id not in self.field_agents and streamer_id not in self.gps_agents:
                    self.streamers.pop(streamer_id, None)
                await ws.close(code=1013, reason="Não foi possível iniciar a sessão")
                raise
        await self.broadcast_streamer(streamer_id)

    async def _stop_video(self, streamer_id: str) -> None:
        await self.streamer_relay.stop_for_streamer(streamer_id)
        receiver = self.srtla_receivers.get(streamer_id)
        if receiver:
            await receiver.stop()
            self.srtla_receivers.pop(streamer_id, None)
        self.port_allocator.release(streamer_id)

    async def disconnect_field(self, streamer_id: str, ws: WebSocket, source: str = "field") -> None:
        async with self._lock:
            sessions = self.gps_agents if source == "gps" else self.field_agents
            if sessions.get(streamer_id) is not ws:
                return  # A late disconnect must not remove the replacement session.
            sessions.pop(streamer_id, None)
            if source == "field":
                await self._stop_video(streamer_id)
                if streamer_id in self.streamers:
                    previous = self.streamers[streamer_id].health.state
                    self.streamers[streamer_id].health = HealthStatus(state=HealthState.DOWN, message="Agente desconectado")
                    await self._notify_obs(streamer_id, previous)
            if streamer_id not in self.field_agents and streamer_id not in self.gps_agents:
                await self._remove_live(streamer_id)
                return
        await self.broadcast_streamer(streamer_id)

    async def remove_streamer(self, streamer_id: str) -> None:
        async with self._lock:
            for sessions in (self.field_agents, self.gps_agents):
                ws = sessions.pop(streamer_id, None)
                if ws:
                    await ws.close(code=1008, reason="Removido pelo admin")
            await self._stop_video(streamer_id)
            await self._remove_live(streamer_id)

    async def _remove_live(self, streamer_id: str) -> None:
        self.streamers.pop(streamer_id, None)
        self._gps_times.pop(streamer_id, None)
        self._gps_sources.pop(streamer_id, None)
        task = self._geocoding.pop(streamer_id, None)
        if task:
            task.cancel()
        await self.broadcast_to_dashboards(DashboardUpdate(
            type="streamer_offline", data={"streamer_id": streamer_id}))

    async def broadcast_streamer(self, streamer_id: str) -> None:
        streamer = self.streamers.get(streamer_id)
        if streamer:
            await self.broadcast_to_dashboards(DashboardUpdate(type="streamer_update", data={
                "streamer_id": streamer_id, "streamer": streamer.model_dump(mode="json")}))

    async def update_gps(self, streamer_id: str, gps: GPSPosition,
                         recorded_at: datetime, source: str = "gps") -> bool:
        now = datetime.now(timezone.utc)
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        age = (now - recorded_at).total_seconds()
        if age > 60 or age < -30 or recorded_at <= self._gps_times.get(streamer_id, datetime.min.replace(tzinfo=timezone.utc)):
            return False
        last_gps = self._gps_times.get(streamer_id)
        if source == "field" and self._gps_sources.get(streamer_id) == "gps" and last_gps and (now - last_gps).total_seconds() < 15:
            return False
        streamer = self.streamers.get(streamer_id)
        if not streamer:
            return False
        self._gps_times[streamer_id] = recorded_at
        self._gps_sources[streamer_id] = source
        streamer.gps = gps
        streamer.updated_at = now
        task = self._geocoding.get(streamer_id)
        if task is None or task.done():
            self._geocoding[streamer_id] = asyncio.create_task(self._update_location(streamer_id, gps))
        return True

    async def handle_field_message(self, streamer_id: str, raw: str,
                                   ws: WebSocket = None, source: str = "field") -> None:
        sessions = self.gps_agents if source == "gps" else self.field_agents
        if ws is not None and sessions.get(streamer_id) is not ws:
            return
        streamer = self.streamers.get(streamer_id)
        if not streamer:
            return
        try:
            msg = ProtocolMessage.model_validate_json(raw)
            if msg.streamer_id != streamer_id:
                return
            if msg.type == MessageType.GPS:
                recorded_at = msg.data.get("recorded_at")
                if recorded_at:
                    recorded_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
                if not await self.update_gps(streamer_id, GPSPosition(**msg.data), recorded_at or msg.timestamp, source):
                    return
            elif source == "field" and msg.type == MessageType.HARDWARE:
                streamer.hardware = HardwareMetrics(**msg.data)
            elif source == "field" and msg.type == MessageType.NETWORK:
                streamer.network_links = [NetworkLink(**link) for link in msg.data.get("links", [])]
            elif source == "field" and msg.type == MessageType.STARLINK:
                streamer.starlink = StarlinkMetrics(**msg.data)
            else:
                return  # Health comes from received video, never from client claims.
        except (ValidationError, ValueError, TypeError, AttributeError):
            log.warning("Telemetria inválida de %s", streamer_id)
            return
        streamer.updated_at = datetime.now(timezone.utc)
        await self.broadcast_streamer(streamer_id)

    async def _update_location(self, streamer_id: str, gps: GPSPosition) -> None:
        location = await reverse_geocode(streamer_id, gps.lat, gps.lng)
        streamer = self.streamers.get(streamer_id)
        if streamer and location:
            streamer.location_name = location

    async def _maintenance(self) -> None:
        while True:
            await asyncio.sleep(settings.health.check_interval_s)
            for sid, streamer in list(self.streamers.items()):
                relay = self.streamer_relay.relays.get(sid)
                if relay:
                    previous = streamer.health.state
                    streamer.health = relay.health()
                    await self._notify_obs(sid, previous)
                    await self.broadcast_streamer(sid)
                elif sid not in self.field_agents and sid not in self.gps_agents:
                    if (datetime.now(timezone.utc) - streamer.updated_at).total_seconds() > 30:
                        await self._remove_live(sid)

    async def _notify_obs(self, sid: str, previous: HealthState) -> None:
        streamer = self.streamers.get(sid)
        if not self._obs or sid != settings.obs.streamer_id or not streamer:
            return
        from ratonet.server.health import StreamState
        if previous != streamer.health.state and streamer.health.state != HealthState.UNKNOWN:
            old = StreamState(previous.value) if previous != HealthState.UNKNOWN else StreamState.DOWN
            await self._obs.on_state_change(sid, old, StreamState(streamer.health.state.value), streamer.health.score)


manager = ConnectionManager()
