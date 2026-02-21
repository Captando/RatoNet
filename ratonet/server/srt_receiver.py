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


class PortAllocator:
    """Aloca portas SRT por streamer (range dinâmico).

    Cada streamer recebe um bloco de portas contíguas para seus links SRT.
    Ex: streamer 0 → 9000-9003, streamer 1 → 9004-9007, etc.
    """

    def __init__(self, base_port: int = 9000, ports_per_streamer: int = 4) -> None:
        self.base_port = base_port
        self.ports_per_streamer = ports_per_streamer
        self.allocations: Dict[str, int] = {}  # streamer_id → base_port alocado
        self._next_slot = 0

    def allocate(self, streamer_id: str) -> int:
        """Retorna base_port para o streamer (aloca se necessário)."""
        if streamer_id in self.allocations:
            return self.allocations[streamer_id]
        port = self.base_port + (self._next_slot * self.ports_per_streamer)
        self.allocations[streamer_id] = port
        self._next_slot += 1
        log.info("Porta SRT alocada para %s: %d-%d", streamer_id[:8], port, port + self.ports_per_streamer - 1)
        return port

    def release(self, streamer_id: str) -> None:
        """Libera portas de um streamer."""
        released = self.allocations.pop(streamer_id, None)
        if released is not None:
            log.info("Porta SRT liberada para %s: %d", streamer_id[:8], released)

    def get_port(self, streamer_id: str) -> Optional[int]:
        """Retorna porta alocada (ou None se não alocada)."""
        return self.allocations.get(streamer_id)


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


class SRTLAReceiver:
    """Receptor SRTLA (protocolo BELABOX).

    srtla_rec recebe pacotes bonded de múltiplos IPs fonte,
    remonta em um stream SRT unificado e encaminha localmente.
    Binário: srtla_rec <listen_port> <forward_host> <forward_port>
    """

    def __init__(
        self,
        listen_port: int = 5001,
        forward_srt_port: int = 9000,
        binary_path: str = "",
        passphrase: str = "",
        latency_ms: int = 500,
    ) -> None:
        self.listen_port = listen_port
        self.forward_srt_port = forward_srt_port
        self.binary_path = binary_path
        self.passphrase = passphrase
        self.latency_ms = latency_ms
        self._rec_process: Optional[asyncio.subprocess.Process] = None
        self._slt_process: Optional[asyncio.subprocess.Process] = None
        self._running = False
        self.active = False

    def _resolve_binary(self) -> Optional[str]:
        """Encontra binário srtla_rec."""
        if self.binary_path:
            return self.binary_path if shutil.which(self.binary_path) or __import__("os").path.isfile(self.binary_path) else None
        return shutil.which("srtla_rec")

    async def start(self) -> bool:
        """Lança srtla_rec + srt-live-transmit. Retorna True se iniciou."""
        binary = self._resolve_binary()
        if not binary:
            log.warning("srtla_rec não encontrado — SRTLA receiver desabilitado")
            return False

        # 1. srtla_rec: recebe UDP bonded, encaminha SRT unificado para localhost
        cmd_rec = [binary, str(self.listen_port), "127.0.0.1", str(self.forward_srt_port)]
        log.info("Iniciando srtla_rec: porta %d → 127.0.0.1:%d", self.listen_port, self.forward_srt_port)

        self._rec_process = await asyncio.create_subprocess_exec(
            *cmd_rec,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 2. srt-live-transmit: recebe SRT do srtla_rec e encaminha para relay via UDP
        if shutil.which("srt-live-transmit"):
            srt_params = f"mode=listener&latency={self.latency_ms * 1000}"
            if self.passphrase:
                srt_params += f"&passphrase={self.passphrase}"
            srt_url = f"srt://0.0.0.0:{self.forward_srt_port}?{srt_params}"
            relay_udp = f"udp://127.0.0.1:{self.forward_srt_port + 1000}"

            cmd_slt = ["srt-live-transmit", srt_url, relay_udp, "-v"]
            log.info("Iniciando srt-live-transmit: %d → UDP %d", self.forward_srt_port, self.forward_srt_port + 1000)

            self._slt_process = await asyncio.create_subprocess_exec(
                *cmd_slt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        self._running = True
        self.active = True
        asyncio.create_task(self._monitor())
        return True

    async def stop(self) -> None:
        """Para srtla_rec e srt-live-transmit."""
        self._running = False
        self.active = False
        for proc in [self._rec_process, self._slt_process]:
            if proc:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
        self._rec_process = None
        self._slt_process = None
        log.info("SRTLA receiver parado")

    async def _monitor(self) -> None:
        """Monitora processos e reinicia se necessário."""
        restart_count = 0
        while self._running:
            await asyncio.sleep(3)

            # Verifica srtla_rec
            if self._rec_process and self._rec_process.returncode is not None:
                if not self._running:
                    break
                restart_count += 1
                if restart_count > 10:
                    log.error("srtla_rec: máximo de restarts excedido")
                    self._running = False
                    self.active = False
                    break
                log.warning("srtla_rec morreu, reiniciando (%d/10)...", restart_count)
                self.active = False
                await asyncio.sleep(2)
                await self.start()

    def get_status(self) -> Dict[str, Any]:
        """Status do receiver SRTLA."""
        return {
            "mode": "srtla",
            "active": self.active,
            "listen_port": self.listen_port,
            "forward_port": self.forward_srt_port,
            "total_links": 1,
            "active_links": 1 if self.active else 0,
        }
