"""Receptor SRT multi-link na VPS.

Escuta N portas SRT (uma por sub-stream/interface do campo).
Monitora estatísticas de cada link e seleciona o melhor para relay.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any, Callable, Dict, List, Optional

from ratonet.common.logger import get_logger
from ratonet.config import settings

log = get_logger("srt_receiver")


class SRTLink:
    """Representa um link SRT receptor individual."""

    def __init__(self, port: int, link_id: int) -> None:
        self.port = port
        self.link_id = link_id
        self.active = False
        self.last_seen = 0.0
        self.bitrate_kbps = 0.0
        self.rtt_ms = 0.0
        self.packet_loss_pct = 0.0
        self.score = 0

        self._process: Optional[asyncio.subprocess.Process] = None
        self._output_pipe: Optional[str] = None

    def calculate_score(self) -> int:
        """Calcula score de qualidade deste link receptor."""
        if not self.active:
            return 0

        score = 100
        staleness = time.time() - self.last_seen
        if staleness > 10:
            return 0
        elif staleness > 5:
            score -= 30

        if self.rtt_ms > 200:
            score -= 30
        elif self.rtt_ms > 100:
            score -= 15

        if self.packet_loss_pct > 5:
            score -= 30
        elif self.packet_loss_pct > 1:
            score -= 10

        self.score = max(0, min(100, score))
        return self.score


class SRTReceiver:
    """Gerencia múltiplos listeners SRT."""

    def __init__(
        self,
        base_port: int = 9000,
        max_links: int = 4,
        latency_ms: int = 500,
        passphrase: str = "",
        output_callback: Optional[Callable] = None,
    ) -> None:
        self.base_port = base_port
        self.max_links = max_links
        self.latency_ms = latency_ms
        self.passphrase = passphrase
        self.output_callback = output_callback

        self.links: List[SRTLink] = []
        self._processes: List[Optional[asyncio.subprocess.Process]] = []
        self._running = False

    async def start(self) -> None:
        """Inicia listeners SRT em todas as portas."""
        if not shutil.which("srt-live-transmit"):
            log.warning(
                "srt-live-transmit não encontrado — "
                "SRT receiver operará em modo simulado"
            )

        self._running = True
        self.links = []

        for i in range(self.max_links):
            port = self.base_port + i
            link = SRTLink(port=port, link_id=i)
            self.links.append(link)

        log.info(
            "SRT Receiver: escutando em portas %d-%d (%d links)",
            self.base_port,
            self.base_port + self.max_links - 1,
            self.max_links,
        )

        # Inicia listeners
        tasks = [self._listen_link(link) for link in self.links]
        asyncio.gather(*tasks)

        # Monitor de saúde
        asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Para todos os listeners."""
        self._running = False
        for link in self.links:
            if link._process:
                link._process.terminate()
                try:
                    await asyncio.wait_for(link._process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    link._process.kill()
        log.info("SRT Receiver parado")

    async def _listen_link(self, link: SRTLink) -> None:
        """Escuta SRT em uma porta específica."""
        srt_params = f"mode=listener&latency={self.latency_ms * 1000}"
        if self.passphrase:
            srt_params += f"&passphrase={self.passphrase}"

        srt_url = f"srt://0.0.0.0:{link.port}?{srt_params}"
        local_udp = f"udp://127.0.0.1:{link.port + 1000}"

        while self._running:
            try:
                if shutil.which("srt-live-transmit"):
                    cmd = ["srt-live-transmit", srt_url, local_udp, "-v"]
                    log.info("[Link %d] Escutando SRT em :%d", link.link_id, link.port)

                    link._process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    link.active = True
                    link.last_seen = time.time()

                    await link._process.wait()
                    link.active = False

                    if self._running:
                        log.warning("[Link %d] SRT desconectou, re-escutando...", link.link_id)
                        await asyncio.sleep(1)
                else:
                    # Modo simulado — apenas marca como escutando
                    log.info("[Link %d] Modo simulado (porta %d)", link.link_id, link.port)
                    link.active = False
                    await asyncio.sleep(30)

            except Exception as e:
                log.error("[Link %d] Erro: %s", link.link_id, e)
                link.active = False
                await asyncio.sleep(3)

    async def _monitor_loop(self) -> None:
        """Monitora saúde dos links periodicamente."""
        while self._running:
            await asyncio.sleep(2)
            for link in self.links:
                link.calculate_score()

    def get_best_link(self) -> Optional[SRTLink]:
        """Retorna o link com melhor score."""
        active = [l for l in self.links if l.active]
        if not active:
            return None
        return max(active, key=lambda l: l.score)

    def get_status(self) -> Dict[str, Any]:
        """Retorna status de todos os links."""
        return {
            "total_links": len(self.links),
            "active_links": sum(1 for l in self.links if l.active),
            "links": [
                {
                    "id": l.link_id,
                    "port": l.port,
                    "active": l.active,
                    "score": l.score,
                    "bitrate_kbps": l.bitrate_kbps,
                    "rtt_ms": l.rtt_ms,
                    "packet_loss_pct": l.packet_loss_pct,
                }
                for l in self.links
            ],
        }
