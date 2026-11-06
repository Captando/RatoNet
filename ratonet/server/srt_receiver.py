"""Bounded port allocation and optional per-streamer SRTLA transport."""

from __future__ import annotations

import asyncio
import shutil
from typing import Dict, Optional

from ratonet.common.logger import get_logger

log = get_logger("srt_receiver")


class PortAllocator:
    def __init__(self, base_port: int = 9000, ports_per_streamer: int = 4,
                 max_streamers: int = 25) -> None:
        if base_port < 1 or ports_per_streamer < 2 or max_streamers < 1:
            raise ValueError("Intervalo de portas inválido")
        if base_port + ports_per_streamer * max_streamers - 1 > 65535:
            raise ValueError("Intervalo excede 65535")
        self.base_port = base_port
        self.ports_per_streamer = ports_per_streamer
        self.max_streamers = max_streamers
        self.allocations: Dict[str, int] = {}

    def allocate(self, streamer_id: str) -> int:
        if streamer_id in self.allocations:
            return self.allocations[streamer_id]
        used = set(self.allocations.values())
        for slot in range(self.max_streamers):
            port = self.base_port + slot * self.ports_per_streamer
            if port not in used:
                self.allocations[streamer_id] = port
                return port
        raise RuntimeError("Capacidade de vídeo esgotada")

    def release(self, streamer_id: str) -> None:
        self.allocations.pop(streamer_id, None)

    def get_port(self, streamer_id: str) -> Optional[int]:
        return self.allocations.get(streamer_id)


class SRTLAReceiver:
    """srtla_rec forwards into the one FFmpeg listener owned by the streamer."""

    def __init__(self, listen_port: int, forward_srt_port: int, binary_path: str = "") -> None:
        self.listen_port = listen_port
        self.forward_srt_port = forward_srt_port
        self.binary = shutil.which(binary_path or "srtla_rec")
        self._process = None
        self._task = None

    async def start(self) -> bool:
        if not self.binary:
            return False
        await self._launch()
        self._task = asyncio.create_task(self._monitor())
        return True

    async def _launch(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            self.binary, str(self.listen_port), "127.0.0.1", str(self.forward_srt_port),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )

    async def _monitor(self) -> None:
        while True:
            code = await self._process.wait()
            log.warning("SRTLA :%d terminou (%d); reiniciando", self.listen_port, code)
            await asyncio.sleep(3)
            await self._launch()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), 5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._process = None
