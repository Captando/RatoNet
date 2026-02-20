"""Monitor de qualidade de interfaces de rede.

Mede RTT, jitter, packet loss e calcula score de qualidade por link.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

import psutil

from ratonet.common.logger import get_logger
from ratonet.common.protocol import MessageType, ProtocolMessage

log = get_logger("network")

# Alvo de ping para medir qualidade (DNS público)
PING_TARGET = "8.8.8.8"
PING_COUNT = 3


def detect_interfaces() -> List[Dict[str, str]]:
    """Detecta interfaces de rede ativas com IP atribuído."""
    interfaces = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()

    for iface, addr_list in addrs.items():
        # Pula loopback e interfaces down
        if iface.startswith("lo") or iface == "lo0":
            continue
        stat = stats.get(iface)
        if not stat or not stat.isup:
            continue

        # Verifica se tem IPv4
        ipv4 = None
        for addr in addr_list:
            if addr.family.name == "AF_INET" and addr.address != "127.0.0.1":
                ipv4 = addr.address
                break

        if not ipv4:
            continue

        # Classifica tipo de interface
        iface_type = _classify_interface(iface)
        interfaces.append({
            "interface": iface,
            "type": iface_type,
            "ip": ipv4,
        })

    return interfaces


def _classify_interface(name: str) -> str:
    """Classifica o tipo de interface pelo nome."""
    name_lower = name.lower()
    if any(x in name_lower for x in ["wwan", "ppp", "usb", "cdc", "qmi"]):
        return "4g"
    elif any(x in name_lower for x in ["wlan", "wlp", "wifi", "ath"]):
        return "wifi"
    elif any(x in name_lower for x in ["eth", "enp", "eno", "en0"]):
        return "ethernet"
    elif any(x in name_lower for x in ["tun", "tap", "wg", "vti"]):
        return "vpn"
    return "unknown"


async def ping_interface(
    interface: str,
    target: str = PING_TARGET,
    count: int = PING_COUNT,
) -> Dict[str, float]:
    """Faz ping pelo interface específico e retorna métricas.

    Retorna: rtt_ms, jitter_ms, packet_loss_pct
    """
    try:
        # -I bind a interface específica (Linux). No macOS usa -b.
        import platform
        if platform.system() == "Darwin":
            cmd = ["ping", "-c", str(count), "-t", "3", target]
        else:
            cmd = ["ping", "-c", str(count), "-W", "3", "-I", interface, target]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        output = stdout.decode()

        return _parse_ping_output(output, count)
    except asyncio.TimeoutError:
        return {"rtt_ms": 0.0, "jitter_ms": 0.0, "packet_loss_pct": 100.0}
    except Exception as e:
        log.warning("Erro no ping via %s: %s", interface, e)
        return {"rtt_ms": 0.0, "jitter_ms": 0.0, "packet_loss_pct": 100.0}


def _parse_ping_output(output: str, count: int) -> Dict[str, float]:
    """Parseia output de ping e extrai métricas."""
    result = {"rtt_ms": 0.0, "jitter_ms": 0.0, "packet_loss_pct": 100.0}

    # Packet loss: "3 packets transmitted, 3 received, 0% packet loss"
    loss_match = re.search(r"(\d+)% packet loss", output)
    if loss_match:
        result["packet_loss_pct"] = float(loss_match.group(1))

    # RTT stats: "rtt min/avg/max/mdev = 10.1/12.3/15.0/2.1 ms"
    # Ou: "round-trip min/avg/max/stddev = ..."
    rtt_match = re.search(
        r"(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s*=\s*"
        r"([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
        output,
    )
    if rtt_match:
        result["rtt_ms"] = float(rtt_match.group(2))     # avg
        result["jitter_ms"] = float(rtt_match.group(4))   # mdev/stddev

    return result


def calculate_link_score(
    rtt_ms: float,
    jitter_ms: float,
    packet_loss_pct: float,
) -> int:
    """Calcula score de qualidade do link (0-100).

    Critérios:
    - RTT < 50ms = ótimo, > 200ms = ruim
    - Jitter < 10ms = ótimo, > 50ms = ruim
    - Packet loss 0% = ótimo, > 5% = ruim
    """
    score = 100

    # Penalidade por RTT
    if rtt_ms > 200:
        score -= 40
    elif rtt_ms > 100:
        score -= 25
    elif rtt_ms > 50:
        score -= 10

    # Penalidade por jitter
    if jitter_ms > 50:
        score -= 30
    elif jitter_ms > 20:
        score -= 15
    elif jitter_ms > 10:
        score -= 5

    # Penalidade por packet loss (mais severa)
    if packet_loss_pct >= 10:
        score -= 40
    elif packet_loss_pct >= 5:
        score -= 25
    elif packet_loss_pct > 0:
        score -= int(packet_loss_pct * 3)

    return max(0, min(100, score))


class NetworkMonitor:
    """Monitora qualidade de todas as interfaces de rede."""

    def __init__(
        self,
        streamer_id: str,
        interfaces: Optional[List[str]] = None,
    ) -> None:
        self.streamer_id = streamer_id
        self.forced_interfaces = interfaces or []
        self.links: List[Dict[str, Any]] = []

    async def scan(self) -> List[Dict[str, str]]:
        """Detecta interfaces disponíveis."""
        detected = detect_interfaces()
        if self.forced_interfaces:
            detected = [d for d in detected if d["interface"] in self.forced_interfaces]
        log.info(
            "Interfaces detectadas: %s",
            ", ".join(f'{d["interface"]} ({d["type"]})' for d in detected) or "nenhuma",
        )
        return detected

    async def collect(self) -> List[Dict[str, Any]]:
        """Mede qualidade de cada interface e retorna lista de links."""
        interfaces = await self.scan()

        tasks = []
        for iface in interfaces:
            tasks.append(self._measure_link(iface))

        self.links = await asyncio.gather(*tasks)
        return self.links

    async def _measure_link(self, iface: Dict[str, str]) -> Dict[str, Any]:
        """Mede qualidade de um link específico."""
        ping_result = await ping_interface(iface["interface"])

        # Bandwidth estimado via psutil (bytes/s recentes)
        try:
            counters = psutil.net_io_counters(pernic=True)
            nic = counters.get(iface["interface"])
            bandwidth_mbps = 0.0
            if nic:
                # bytes_sent + bytes_recv dos últimos dados disponíveis
                # (estimativa grosseira, ideal seria medir delta)
                bandwidth_mbps = (nic.bytes_sent + nic.bytes_recv) / 1_000_000
        except Exception:
            bandwidth_mbps = 0.0

        score = calculate_link_score(
            ping_result["rtt_ms"],
            ping_result["jitter_ms"],
            ping_result["packet_loss_pct"],
        )

        return {
            "interface": iface["interface"],
            "type": iface["type"],
            "connected": ping_result["packet_loss_pct"] < 100,
            "rtt_ms": ping_result["rtt_ms"],
            "jitter_ms": ping_result["jitter_ms"],
            "packet_loss_pct": ping_result["packet_loss_pct"],
            "bandwidth_mbps": bandwidth_mbps,
            "score": score,
        }

    def to_protocol_message(self) -> ProtocolMessage:
        """Converte para mensagem do protocolo."""
        return ProtocolMessage.create(
            MessageType.NETWORK,
            self.streamer_id,
            {"links": self.links},
        )
