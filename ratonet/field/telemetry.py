"""Coleta de telemetria do hardware de campo.

Módulos:
- GPS via gpsd (gpsdclient)
- Hardware via psutil (CPU, temp, RAM, bateria)
- Starlink via gRPC (latência, throughput, obstruções)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

import psutil

from ratonet.common.logger import get_logger
from ratonet.common.protocol import MessageType, ProtocolMessage

log = get_logger("telemetry")


class GPSCollector:
    """Coleta dados GPS via gpsd."""

    def __init__(self, host: str = "localhost", port: int = 2947) -> None:
        self.host = host
        self.port = port
        self._client = None
        self._last_data: Dict[str, Any] = {}

    async def start(self) -> None:
        """Conecta ao gpsd."""
        try:
            from gpsdclient import GPSDClient
            self._client = GPSDClient(host=self.host, port=self.port)
            log.info("GPS conectado em %s:%d", self.host, self.port)
        except ImportError:
            log.warning("gpsdclient não instalado — GPS desabilitado")
            self._client = None
        except Exception as e:
            log.warning("Falha ao conectar GPS: %s", e)
            self._client = None

    async def collect(self) -> Dict[str, Any]:
        """Retorna dados GPS atuais."""
        if self._client is None:
            return self._last_data or {
                "lat": 0.0, "lng": 0.0, "speed_kmh": 0.0,
                "altitude_m": 0.0, "heading": 0.0, "satellites": 0, "fix": "none",
            }

        try:
            # gpsdclient é síncrono, roda em thread
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._poll_gps
            )
            if result:
                self._last_data = result
            return self._last_data
        except Exception as e:
            log.warning("Erro ao coletar GPS: %s", e)
            return self._last_data

    def _poll_gps(self) -> Optional[Dict[str, Any]]:
        """Poll síncrono do gpsd (roda em thread)."""
        try:
            for result in self._client.dict_stream(convert_datetime=False):
                if result.get("class") == "TPV":
                    return {
                        "lat": result.get("lat", 0.0),
                        "lng": result.get("lon", 0.0),
                        "speed_kmh": (result.get("speed", 0.0) or 0.0) * 3.6,
                        "altitude_m": result.get("alt", 0.0) or 0.0,
                        "heading": result.get("track", 0.0) or 0.0,
                        "satellites": result.get("nSat", 0) or 0,
                        "fix": {0: "none", 1: "none", 2: "2d", 3: "3d"}.get(
                            result.get("mode", 0), "none"
                        ),
                    }
        except Exception:
            return None


class HardwareCollector:
    """Coleta métricas de hardware via psutil."""

    async def collect(self) -> Dict[str, Any]:
        """Retorna métricas de hardware atuais."""
        data: Dict[str, Any] = {}

        # CPU
        data["cpu_percent"] = psutil.cpu_percent(interval=0)

        # Temperatura
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Pega a primeira temperatura disponível
                for name, entries in temps.items():
                    if entries:
                        data["cpu_temp_c"] = entries[0].current
                        break
                else:
                    data["cpu_temp_c"] = 0.0
            else:
                data["cpu_temp_c"] = 0.0
        except (AttributeError, Exception):
            data["cpu_temp_c"] = 0.0

        # RAM
        mem = psutil.virtual_memory()
        data["ram_percent"] = mem.percent

        # Disco
        disk = psutil.disk_usage("/")
        data["disk_percent"] = disk.percent

        # Bateria
        try:
            battery = psutil.sensors_battery()
            if battery:
                data["battery_percent"] = battery.percent
                data["battery_charging"] = battery.power_plugged or False
            else:
                data["battery_percent"] = None
                data["battery_charging"] = False
        except (AttributeError, Exception):
            data["battery_percent"] = None
            data["battery_charging"] = False

        return data


class StarlinkCollector:
    """Coleta métricas do Starlink via gRPC."""

    def __init__(self, addr: str = "192.168.100.1:9200") -> None:
        self.addr = addr
        self._available = False
        self._last_data: Dict[str, Any] = {}

    async def start(self) -> None:
        """Tenta conectar ao Starlink dish."""
        try:
            import grpc
            channel = grpc.insecure_channel(self.addr)
            # Testa conectividade
            try:
                grpc.channel_ready_future(channel).result(timeout=3)
                self._available = True
                log.info("Starlink dish detectado em %s", self.addr)
            except grpc.FutureTimeoutError:
                log.info("Starlink dish não encontrado em %s — desabilitado", self.addr)
                self._available = False
            finally:
                channel.close()
        except ImportError:
            log.info("grpc não instalado — Starlink desabilitado")
            self._available = False

    async def collect(self) -> Dict[str, Any]:
        """Retorna métricas Starlink atuais."""
        if not self._available:
            return {
                "connected": False, "latency_ms": 0.0,
                "download_mbps": 0.0, "upload_mbps": 0.0,
                "obstruction_pct": 0.0, "uptime_s": 0,
            }

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._poll_starlink
            )
            if result:
                self._last_data = result
            return self._last_data or {
                "connected": False, "latency_ms": 0.0,
                "download_mbps": 0.0, "upload_mbps": 0.0,
                "obstruction_pct": 0.0, "uptime_s": 0,
            }
        except Exception as e:
            log.warning("Erro ao coletar Starlink: %s", e)
            return self._last_data

    def _poll_starlink(self) -> Optional[Dict[str, Any]]:
        """Poll síncrono do Starlink dish (roda em thread)."""
        try:
            import grpc

            channel = grpc.insecure_channel(self.addr)
            # Import dinâmico dos protos do Starlink (spacex.api.device)
            from spacex.api.device import device_pb2, device_pb2_grpc

            stub = device_pb2_grpc.DeviceStub(channel)
            request = device_pb2.Request(get_status={})
            response = stub.Handle(request, timeout=5)

            status = response.dish_get_status
            return {
                "connected": status.state == 1,  # CONNECTED
                "latency_ms": status.pop_ping_latency_ms,
                "download_mbps": status.downlink_throughput_bps / 1_000_000,
                "upload_mbps": status.uplink_throughput_bps / 1_000_000,
                "obstruction_pct": status.obstruction_stats.fraction_obstructed * 100,
                "uptime_s": int(status.device_state.uptime_s),
            }
        except Exception:
            return None


class TelemetryAggregator:
    """Agrega todos os coletores e produz mensagens de telemetria."""

    def __init__(
        self,
        streamer_id: str,
        gps_host: str = "localhost",
        gps_port: int = 2947,
        starlink_addr: str = "192.168.100.1:9200",
    ) -> None:
        self.streamer_id = streamer_id
        self.gps = GPSCollector(gps_host, gps_port)
        self.hardware = HardwareCollector()
        self.starlink = StarlinkCollector(starlink_addr)

    async def start(self) -> None:
        """Inicializa coletores."""
        await self.gps.start()
        await self.starlink.start()
        log.info("Telemetria inicializada para streamer %s", self.streamer_id)

    async def collect_all(self) -> list:
        """Coleta tudo e retorna lista de ProtocolMessages."""
        gps_data, hw_data, sl_data = await asyncio.gather(
            self.gps.collect(),
            self.hardware.collect(),
            self.starlink.collect(),
        )

        messages = [
            ProtocolMessage.create(MessageType.GPS, self.streamer_id, gps_data),
            ProtocolMessage.create(MessageType.HARDWARE, self.streamer_id, hw_data),
            ProtocolMessage.create(MessageType.STARLINK, self.streamer_id, sl_data),
        ]

        return messages
