"""Entry point do Field Agent — agente de campo que roda no hardware de streaming.

Responsável por:
1. Coletar telemetria (GPS, hardware, Starlink)
2. Monitorar qualidade de rede
3. Gerenciar encoder FFmpeg + bonding SRT
4. Enviar tudo via WebSocket para o servidor VPS
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from typing import Optional

import websockets

from ratonet.common.logger import get_logger
from ratonet.common.protocol import MessageType, ProtocolMessage
from ratonet.config import settings
from ratonet.field.network_monitor import NetworkMonitor
from ratonet.field.telemetry import TelemetryAggregator

log = get_logger("field.agent")


class FieldAgent:
    """Agente de campo principal."""

    def __init__(
        self,
        streamer_id: str,
        server_url: str,
        telemetry_interval: float = 1.0,
        network_interval: float = 5.0,
        enable_video: bool = False,
    ) -> None:
        self.streamer_id = streamer_id
        self.server_url = server_url
        self.telemetry_interval = telemetry_interval
        self.network_interval = network_interval
        self.enable_video = enable_video

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False

        # Componentes
        gps_parts = settings.field.gps_device.split(":")
        gps_host = gps_parts[0]
        gps_port = int(gps_parts[1]) if len(gps_parts) > 1 else 2947

        self.telemetry = TelemetryAggregator(
            streamer_id=streamer_id,
            gps_host=gps_host,
            gps_port=gps_port,
            starlink_addr=settings.field.starlink_addr,
        )
        self.network = NetworkMonitor(
            streamer_id=streamer_id,
            interfaces=settings.field.network_interfaces or None,
        )

        # Video (lazy import para evitar dependência quando não usado)
        self._encoder = None
        self._bonding = None

    async def start(self) -> None:
        """Inicia o agente de campo."""
        self._running = True
        log.info("=== RatoNet Field Agent ===")
        log.info("Streamer ID: %s", self.streamer_id)
        log.info("Servidor: %s", self.server_url)

        # Inicializa coletores
        await self.telemetry.start()

        # Inicializa vídeo se habilitado
        if self.enable_video:
            await self._start_video()

        # Loop principal com reconexão
        while self._running:
            try:
                await self._connect_and_run()
            except Exception as e:
                log.error("Conexão perdida: %s — reconectando em 3s", e)
                await asyncio.sleep(3)

    async def stop(self) -> None:
        """Para o agente de campo."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._encoder:
            await self._encoder.stop()
        log.info("Field agent parado")

    async def _connect_and_run(self) -> None:
        """Conecta ao servidor e inicia loops de envio."""
        url = f"{self.server_url}/{self.streamer_id}"
        log.info("Conectando a %s ...", url)

        async with websockets.connect(url) as ws:
            self._ws = ws
            log.info("Conectado ao servidor!")

            # Roda telemetria e network em paralelo
            tasks = [
                asyncio.create_task(self._telemetry_loop()),
                asyncio.create_task(self._network_loop()),
                asyncio.create_task(self._receive_loop()),
            ]

            try:
                await asyncio.gather(*tasks)
            except websockets.ConnectionClosed:
                log.warning("Conexão WebSocket fechada")
                for task in tasks:
                    task.cancel()

    async def _telemetry_loop(self) -> None:
        """Loop de envio de telemetria (GPS + hardware + Starlink)."""
        while self._running and self._ws:
            try:
                messages = await self.telemetry.collect_all()
                for msg in messages:
                    await self._ws.send(msg.to_json())
            except websockets.ConnectionClosed:
                raise
            except Exception as e:
                log.warning("Erro na telemetria: %s", e)

            await asyncio.sleep(self.telemetry_interval)

    async def _network_loop(self) -> None:
        """Loop de monitoramento de rede (menos frequente, pois ping demora)."""
        while self._running and self._ws:
            try:
                await self.network.collect()
                msg = self.network.to_protocol_message()
                await self._ws.send(msg.to_json())
            except websockets.ConnectionClosed:
                raise
            except Exception as e:
                log.warning("Erro no network monitor: %s", e)

            await asyncio.sleep(self.network_interval)

    async def _receive_loop(self) -> None:
        """Recebe comandos do servidor."""
        while self._running and self._ws:
            try:
                raw = await self._ws.recv()
                msg = json.loads(raw)
                log.info("Comando recebido: %s", msg.get("type", "unknown"))
                # TODO: processar comandos (restart encoder, change bitrate, etc.)
            except websockets.ConnectionClosed:
                raise
            except Exception:
                pass

    async def _start_video(self) -> None:
        """Inicializa encoder e bonding (se habilitado)."""
        try:
            from ratonet.field.encoder import SRTEncoder
            from ratonet.field.bonding import NetworkBonding

            self._bonding = NetworkBonding(
                streamer_id=self.streamer_id,
                server_host=self.server_url.replace("ws://", "").replace("wss://", "").split(":")[0],
                base_port=settings.srt.base_port,
            )

            self._encoder = SRTEncoder(
                device=settings.field.video_device,
                bitrate=settings.field.video_bitrate,
                resolution=settings.field.video_resolution,
                codec=settings.field.video_codec,
                bonding=self._bonding,
            )

            await self._encoder.start()
            log.info("Video pipeline iniciado")
        except ImportError as e:
            log.warning("Módulos de vídeo não disponíveis: %s", e)
        except Exception as e:
            log.error("Erro ao iniciar vídeo: %s", e)


def main() -> None:
    """Entry point CLI."""
    parser = argparse.ArgumentParser(description="RatoNet Field Agent")
    parser.add_argument(
        "--id", required=True, help="ID do streamer (ex: '1', 'ricardo')"
    )
    parser.add_argument(
        "--server", default=settings.field.server_ws_url,
        help=f"URL WebSocket do servidor (default: {settings.field.server_ws_url})",
    )
    parser.add_argument(
        "--interval", type=float, default=settings.field.telemetry_interval_s,
        help="Intervalo de telemetria em segundos",
    )
    parser.add_argument(
        "--video", action="store_true",
        help="Habilitar pipeline de vídeo (FFmpeg + SRT)",
    )
    args = parser.parse_args()

    agent = FieldAgent(
        streamer_id=args.id,
        server_url=args.server,
        telemetry_interval=args.interval,
        enable_video=args.video,
    )

    loop = asyncio.new_event_loop()

    def shutdown(sig, frame):
        log.info("Sinal %s recebido, parando...", sig)
        loop.create_task(agent.stop())

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        loop.run_until_complete(agent.start())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
