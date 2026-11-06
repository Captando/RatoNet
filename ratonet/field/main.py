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
from urllib.parse import urlencode, urlsplit, urlunsplit

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
        api_key: str = "",
        telemetry_interval: float = 1.0,
        network_interval: float = 5.0,
        enable_video: bool = False,
    ) -> None:
        self.streamer_id = streamer_id
        self.server_url = server_url
        self.api_key = api_key
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

        # Loop principal com reconexão
        while self._running:
            try:
                await self._connect_and_run()
            except websockets.ConnectionClosed as e:
                code = e.rcvd.code if e.rcvd else None
                if code in (4000, 4001, 4003, 1008):
                    log.error("Sessão encerrada pelo servidor (%s)", code)
                    self._running = False
                    break
                await asyncio.sleep(3)
            except Exception as e:
                log.error("Conexão perdida: %s — reconectando em 3s", e)
                await asyncio.sleep(3)

    async def stop(self) -> None:
        """Para o agente de campo."""
        self._running = False
        if self._ws:
            await self._ws.close()
        await self._stop_video()
        log.info("Field agent parado")

    async def _connect_and_run(self) -> None:
        """Conecta ao servidor e inicia loops de envio."""
        from ratonet.field.bonding import SRTLASender
        parts = urlsplit(self.server_url)
        use_srtla = settings.srtla.enabled and SRTLASender(
            settings.srtla.send_port, parts.hostname, 0,
            binary_path=settings.srtla.binary_path)._resolve_binary()
        query = urlencode({"key": self.api_key, "source": "field",
                           "video": str(self.enable_video).lower(),
                           "transport": "srtla" if use_srtla else "srt"})
        url = urlunsplit((parts.scheme, parts.netloc,
                         parts.path.rstrip("/") + "/" + self.streamer_id, query, ""))
        log.info("Conectando a %s ...", url.split("?")[0])

        async with websockets.connect(url) as ws:
            self._ws = ws
            log.info("Conectado ao servidor!")

            tasks = []
            try:
                ready = json.loads(await asyncio.wait_for(ws.recv(), 20))
                if ready.get("type") != "session_ready":
                    raise RuntimeError("Servidor não negociou a sessão")
                if self.enable_video:
                    await self._start_video(ready["data"]["video"])
                tasks = [asyncio.create_task(self._telemetry_loop()),
                         asyncio.create_task(self._network_loop()),
                         asyncio.create_task(self._receive_loop())]
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await self._stop_video()
                self._ws = None

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

    async def _start_video(self, config: dict) -> None:
        """Starts video only after the server has reserved the authenticated input."""
        from ratonet.field.encoder import SRTEncoder
        from ratonet.field.bonding import SRTLASender

        if not config:
            raise RuntimeError("Servidor não disponibilizou entrada de vídeo")
        host = urlsplit(self.server_url).hostname
        url_host = f"[{host}]" if ":" in host else host
        output = f"srt://{url_host}:{config['port']}?mode=caller"
        if config["transport"] == "srtla":
            self._bonding = SRTLASender(
                settings.srtla.send_port, host, config["port"],
                settings.field.network_interfaces, settings.srtla.binary_path)
            if not await self._bonding.start():
                raise RuntimeError("Não foi possível iniciar srtla_send")
            output = self._bonding.get_primary_srt_url()
        self._encoder = SRTEncoder(
            device=settings.field.video_device, bitrate=settings.field.video_bitrate,
            resolution=settings.field.video_resolution, codec=settings.field.video_codec,
            srt_url=output, latency_ms=config["latency_ms"], passphrase=config["passphrase"])
        await self._encoder.start()

    async def _stop_video(self) -> None:
        if self._encoder:
            await self._encoder.stop()
            self._encoder = None
        if self._bonding:
            await self._bonding.stop()
            self._bonding = None


def main() -> None:
    """Entry point CLI."""
    parser = argparse.ArgumentParser(description="RatoNet Field Agent")
    parser.add_argument(
        "--id", default=settings.field.streamer_id, help="ID do streamer (ou FIELD_STREAMER_ID)"
    )
    parser.add_argument(
        "--key", default=settings.field.api_key, help="API key do streamer (ou FIELD_API_KEY)"
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
    if not args.id or not args.key:
        parser.error("Informe --id e --key ou FIELD_STREAMER_ID e FIELD_API_KEY no .env")

    agent = FieldAgent(
        streamer_id=args.id,
        server_url=args.server,
        api_key=args.key,
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
