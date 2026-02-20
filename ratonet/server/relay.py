"""Relay de vídeo para plataformas de streaming via RTMP.

Recebe stream local (via SRT/UDP) e faz relay para Twitch, YouTube, etc.
Suporta múltiplos destinos simultâneos (multistream).
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any, Dict, List, Optional

from ratonet.common.logger import get_logger
from ratonet.config import settings

log = get_logger("relay")


class RTMPRelay:
    """Relay de um stream local para um destino RTMP."""

    def __init__(
        self,
        name: str,
        rtmp_url: str,
        input_url: str = "udp://127.0.0.1:10000",
        transmux: bool = True,
    ) -> None:
        self.name = name
        self.rtmp_url = rtmp_url
        self.input_url = input_url
        self.transmux = transmux

        self.active = False
        self.uptime_s = 0.0
        self._process: Optional[asyncio.subprocess.Process] = None
        self._running = False
        self._restart_count = 0

    def _build_command(self) -> List[str]:
        """Constrói comando FFmpeg para relay."""
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]

        # Input
        cmd += ["-i", self.input_url]

        if self.transmux:
            # Transmux apenas (sem re-encode) — mínima latência e CPU
            cmd += ["-c", "copy"]
        else:
            # Re-encode (caso precise mudar formato)
            cmd += [
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-b:v", "4000k",
                "-c:a", "aac",
                "-b:a", "128k",
            ]

        # Output RTMP
        cmd += ["-f", "flv", self.rtmp_url]

        return cmd

    async def start(self) -> None:
        """Inicia o relay RTMP."""
        if not self.rtmp_url:
            log.warning("[%s] URL RTMP vazia — relay desabilitado", self.name)
            return

        if not shutil.which("ffmpeg"):
            log.error("FFmpeg não encontrado no PATH!")
            return

        self._running = True
        self._restart_count = 0
        await self._launch()
        asyncio.create_task(self._health_monitor())

    async def stop(self) -> None:
        """Para o relay."""
        self._running = False
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
        self.active = False
        log.info("[%s] Relay parado", self.name)

    async def _launch(self) -> None:
        """Lança processo FFmpeg de relay."""
        cmd = self._build_command()
        # Mascara a stream key no log
        safe_url = self.rtmp_url.split("/")
        safe_url[-1] = "***"
        log.info("[%s] Relay → %s", self.name, "/".join(safe_url))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.active = True

    async def _health_monitor(self) -> None:
        """Monitora e reinicia relay se necessário."""
        while self._running:
            await asyncio.sleep(3)

            if self._process and self._process.returncode is not None:
                if not self._running:
                    break

                self._restart_count += 1
                if self._restart_count > 10:
                    log.error("[%s] Máximo de restarts excedido", self.name)
                    self._running = False
                    break

                log.warning(
                    "[%s] Relay morreu, reiniciando (%d/10)...",
                    self.name, self._restart_count,
                )
                self.active = False
                await asyncio.sleep(2)
                await self._launch()

    def get_status(self) -> Dict[str, Any]:
        """Status do relay."""
        return {
            "name": self.name,
            "active": self.active,
            "restarts": self._restart_count,
        }


class RelayManager:
    """Gerencia múltiplos relays RTMP simultâneos (multistream)."""

    def __init__(self, input_url: str = "udp://127.0.0.1:10000") -> None:
        self.input_url = input_url
        self.relays: List[RTMPRelay] = []

    def add_destination(
        self, name: str, rtmp_url: str, transmux: bool = True
    ) -> None:
        """Adiciona destino RTMP."""
        relay = RTMPRelay(
            name=name,
            rtmp_url=rtmp_url,
            input_url=self.input_url,
            transmux=transmux,
        )
        self.relays.append(relay)
        log.info("Destino adicionado: %s", name)

    async def start_all(self) -> None:
        """Inicia todos os relays."""
        tasks = [r.start() for r in self.relays]
        await asyncio.gather(*tasks)
        active = sum(1 for r in self.relays if r.active)
        log.info("Relays ativos: %d/%d", active, len(self.relays))

    async def stop_all(self) -> None:
        """Para todos os relays."""
        tasks = [r.stop() for r in self.relays]
        await asyncio.gather(*tasks)
        log.info("Todos os relays parados")

    def get_status(self) -> Dict[str, Any]:
        """Status de todos os relays."""
        return {
            "total": len(self.relays),
            "active": sum(1 for r in self.relays if r.active),
            "destinations": [r.get_status() for r in self.relays],
        }

    @classmethod
    def from_config(cls) -> RelayManager:
        """Cria RelayManager a partir da configuração."""
        manager = cls()

        if settings.rtmp.primary_url:
            manager.add_destination("Primary", settings.rtmp.primary_url)

        if settings.rtmp.secondary_url:
            manager.add_destination("Secondary", settings.rtmp.secondary_url)

        return manager
