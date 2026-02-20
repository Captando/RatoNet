"""Bonding de múltiplas interfaces de rede para SRT.

Estratégia: múltiplos SRT sub-streams, um por interface de rede.
Cada interface envia um SRT stream independente para a VPS.
O SRT já tem ARQ (retransmissão automática) embutido — cada link é resiliente.
A VPS recebe todos e seleciona o melhor baseado na qualidade.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any, Dict, List, Optional

from ratonet.common.logger import get_logger
from ratonet.field.network_monitor import NetworkMonitor, detect_interfaces

log = get_logger("bonding")


class BondedLink:
    """Representa um link SRT ativo em uma interface específica."""

    def __init__(
        self,
        interface: str,
        iface_type: str,
        server_host: str,
        srt_port: int,
        latency_ms: int = 500,
    ) -> None:
        self.interface = interface
        self.iface_type = iface_type
        self.server_host = server_host
        self.srt_port = srt_port
        self.latency_ms = latency_ms

        self.active = False
        self.score = 0
        self._process: Optional[asyncio.subprocess.Process] = None

    @property
    def srt_url(self) -> str:
        """URL SRT para este link."""
        return f"{self.server_host}:{self.srt_port}"

    def srt_url_with_params(self) -> str:
        """URL SRT completa com parâmetros."""
        return (
            f"srt://{self.server_host}:{self.srt_port}"
            f"?mode=caller&latency={self.latency_ms * 1000}"
        )

    async def start_relay(self, input_pipe: str) -> None:
        """Inicia srt-live-transmit para este link.

        Recebe de um pipe local e envia via SRT pelo interface específico.
        """
        cmd = [
            "srt-live-transmit",
            f"udp://:{input_pipe}",
            self.srt_url_with_params(),
            "-v",
        ]

        log.info("[%s] Iniciando SRT relay → %s:%d", self.interface, self.server_host, self.srt_port)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self.active = True
        except FileNotFoundError:
            log.warning("srt-live-transmit não encontrado — relay desabilitado para %s", self.interface)
            self.active = False

    async def stop(self) -> None:
        """Para o relay SRT deste link."""
        self.active = False
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

    def update_score(self, score: int) -> None:
        """Atualiza score de qualidade deste link."""
        self.score = score


class NetworkBonding:
    """Gerencia bonding de múltiplas interfaces para SRT."""

    def __init__(
        self,
        streamer_id: str,
        server_host: str,
        base_port: int = 9000,
        latency_ms: int = 500,
        forced_interfaces: Optional[List[str]] = None,
    ) -> None:
        self.streamer_id = streamer_id
        self.server_host = server_host
        self.base_port = base_port
        self.latency_ms = latency_ms
        self.forced_interfaces = forced_interfaces

        self.links: List[BondedLink] = []
        self._monitor = NetworkMonitor(streamer_id, forced_interfaces)

    async def discover_and_setup(self) -> List[BondedLink]:
        """Detecta interfaces e cria links bonded."""
        interfaces = detect_interfaces()

        if self.forced_interfaces:
            interfaces = [i for i in interfaces if i["interface"] in self.forced_interfaces]

        self.links = []
        for idx, iface in enumerate(interfaces):
            link = BondedLink(
                interface=iface["interface"],
                iface_type=iface["type"],
                server_host=self.server_host,
                srt_port=self.base_port + idx,
                latency_ms=self.latency_ms,
            )
            self.links.append(link)

        log.info(
            "Bonding configurado: %d links — %s",
            len(self.links),
            ", ".join(f"{l.interface}→:{l.srt_port}" for l in self.links),
        )
        return self.links

    def get_primary_srt_url(self) -> Optional[str]:
        """Retorna URL SRT do melhor link ativo."""
        active = [l for l in self.links if l.active]
        if not active:
            # Fallback: retorna o primeiro link (mesmo que não ativo)
            if self.links:
                return self.links[0].srt_url
            return None

        # Ordena por score (maior = melhor)
        active.sort(key=lambda l: l.score, reverse=True)
        return active[0].srt_url

    def get_all_srt_urls(self) -> List[str]:
        """Retorna URLs SRT de todos os links."""
        return [l.srt_url for l in self.links]

    async def update_scores(self) -> None:
        """Atualiza scores de qualidade de cada link."""
        network_data = await self._monitor.collect()
        for link in self.links:
            for net in network_data:
                if net["interface"] == link.interface:
                    link.update_score(net["score"])
                    link.active = net["connected"]
                    break

    async def stop_all(self) -> None:
        """Para todos os links."""
        for link in self.links:
            await link.stop()
        log.info("Todos os links bonded parados")

    @property
    def active_count(self) -> int:
        """Número de links ativos."""
        return sum(1 for l in self.links if l.active)

    @property
    def total_count(self) -> int:
        """Total de links configurados."""
        return len(self.links)

    def status_summary(self) -> Dict[str, Any]:
        """Resumo do estado do bonding."""
        return {
            "active_links": self.active_count,
            "total_links": self.total_count,
            "links": [
                {
                    "interface": l.interface,
                    "type": l.iface_type,
                    "port": l.srt_port,
                    "active": l.active,
                    "score": l.score,
                }
                for l in self.links
            ],
        }
