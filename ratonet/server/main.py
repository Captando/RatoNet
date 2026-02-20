"""Entry point do VPS Server — servidor que recebe streams e gerencia a live.

Responsável por:
1. Receber streams SRT de múltiplos links (bonding)
2. Relay para plataformas (Twitch, YouTube) via RTMP
3. Monitorar saúde da stream
4. Controlar OBS para fallback automático
5. Servir dashboard API (FastAPI)
"""

from __future__ import annotations

import argparse
import asyncio
import signal
from typing import Optional

from ratonet.common.logger import get_logger
from ratonet.config import settings

log = get_logger("server")


class VPSServer:
    """Servidor VPS principal que orquestra todos os componentes."""

    def __init__(
        self,
        enable_srt: bool = True,
        enable_relay: bool = True,
        enable_obs: bool = True,
        enable_dashboard: bool = True,
    ) -> None:
        self.enable_srt = enable_srt
        self.enable_relay = enable_relay
        self.enable_obs = enable_obs
        self.enable_dashboard = enable_dashboard

        self._running = False
        self._srt_receiver = None
        self._relay_manager = None
        self._health_monitor = None
        self._obs_controller = None

    async def start(self) -> None:
        """Inicia todos os componentes do servidor."""
        self._running = True
        log.info("=== RatoNet VPS Server ===")

        # 1. OBS Controller (precisa estar pronto antes do health)
        if self.enable_obs:
            await self._start_obs()

        # 2. Health Monitor
        self._start_health()

        # 3. SRT Receiver
        if self.enable_srt:
            await self._start_srt()

        # 4. RTMP Relay
        if self.enable_relay:
            await self._start_relay()

        # 5. Dashboard (FastAPI) — roda como último componente (bloqueia)
        if self.enable_dashboard:
            await self._start_dashboard()
        else:
            # Se não tem dashboard, apenas espera
            while self._running:
                await asyncio.sleep(1)

    async def stop(self) -> None:
        """Para todos os componentes."""
        self._running = False
        log.info("Parando servidor...")

        if self._srt_receiver:
            await self._srt_receiver.stop()
        if self._relay_manager:
            await self._relay_manager.stop_all()
        if self._obs_controller:
            self._obs_controller.disconnect()

        log.info("Servidor parado")

    async def _start_obs(self) -> None:
        """Inicializa OBS Controller."""
        from ratonet.server.obs_controller import OBSController

        self._obs_controller = OBSController.from_config()
        connected = await self._obs_controller.connect()
        if connected:
            log.info("OBS Controller: conectado")
        else:
            log.info("OBS Controller: não conectado (continuando sem fallback OBS)")

    def _start_health(self) -> None:
        """Inicializa Health Monitor."""
        from ratonet.server.health import HealthMonitor

        callback = None
        if self._obs_controller and self._obs_controller.is_connected:
            callback = self._obs_controller.on_state_change

        self._health_monitor = HealthMonitor.from_config(
            streamer_id="main",
            on_state_change=callback,
        )
        log.info("Health Monitor: inicializado")

    async def _start_srt(self) -> None:
        """Inicializa SRT Receiver."""
        from ratonet.server.srt_receiver import SRTReceiver

        self._srt_receiver = SRTReceiver(
            base_port=settings.srt.base_port,
            max_links=settings.srt.max_links,
            latency_ms=settings.srt.latency_ms,
            passphrase=settings.srt.passphrase,
        )
        await self._srt_receiver.start()
        log.info("SRT Receiver: escutando")

        # Loop de atualização do health com dados do SRT
        asyncio.create_task(self._srt_health_loop())

    async def _srt_health_loop(self) -> None:
        """Atualiza health monitor com dados do SRT receiver."""
        while self._running:
            await asyncio.sleep(settings.health.check_interval_s)
            if self._srt_receiver and self._health_monitor:
                status = self._srt_receiver.get_status()
                link_scores = [l["score"] for l in status["links"]]
                active_links = [l for l in status["links"] if l["active"]]

                avg_rtt = 0.0
                avg_loss = 0.0
                total_bitrate = 0.0
                if active_links:
                    avg_rtt = sum(l["rtt_ms"] for l in active_links) / len(active_links)
                    avg_loss = sum(l["packet_loss_pct"] for l in active_links) / len(active_links)
                    total_bitrate = sum(l["bitrate_kbps"] for l in active_links)

                self._health_monitor.update_metrics(
                    active_links=status["active_links"],
                    total_links=status["total_links"],
                    bitrate_kbps=total_bitrate,
                    rtt_avg_ms=avg_rtt,
                    packet_loss_avg=avg_loss,
                    link_scores=link_scores,
                )

    async def _start_relay(self) -> None:
        """Inicializa RTMP Relay."""
        from ratonet.server.relay import RelayManager

        self._relay_manager = RelayManager.from_config()
        if self._relay_manager.relays:
            await self._relay_manager.start_all()
            log.info("RTMP Relay: %d destinos", len(self._relay_manager.relays))
        else:
            log.info("RTMP Relay: nenhum destino configurado (configure RTMP_PRIMARY_URL)")

    async def _start_dashboard(self) -> None:
        """Inicia FastAPI dashboard."""
        import uvicorn

        log.info(
            "Dashboard: http://%s:%d",
            settings.dashboard.host,
            settings.dashboard.port,
        )

        config = uvicorn.Config(
            "ratonet.dashboard.main:app",
            host=settings.dashboard.host,
            port=settings.dashboard.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()


def main() -> None:
    """Entry point CLI."""
    parser = argparse.ArgumentParser(description="RatoNet VPS Server")
    parser.add_argument("--no-srt", action="store_true", help="Desabilitar SRT receiver")
    parser.add_argument("--no-relay", action="store_true", help="Desabilitar RTMP relay")
    parser.add_argument("--no-obs", action="store_true", help="Desabilitar OBS controller")
    parser.add_argument("--no-dashboard", action="store_true", help="Desabilitar dashboard web")
    args = parser.parse_args()

    server = VPSServer(
        enable_srt=not args.no_srt,
        enable_relay=not args.no_relay,
        enable_obs=not args.no_obs,
        enable_dashboard=not args.no_dashboard,
    )

    loop = asyncio.new_event_loop()

    def shutdown(sig, frame):
        log.info("Sinal %s recebido, parando...", sig)
        loop.create_task(server.stop())

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        loop.run_until_complete(server.start())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
