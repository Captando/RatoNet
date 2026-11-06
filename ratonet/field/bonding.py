"""SRTLA sender. Without its binary, the field agent uses direct SRT."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from ratonet.common.logger import get_logger
from ratonet.field.network_monitor import detect_interfaces

log = get_logger("bonding")


class SRTLASender:
    def __init__(self, listen_port: int, server_host: str, server_port: int,
                 interfaces: Optional[List[str]] = None, binary_path: str = "") -> None:
        self.listen_port = listen_port
        self.server_host = server_host
        self.server_port = server_port
        self.interfaces = interfaces or []
        self.binary_path = binary_path
        self._process = None
        self._task = None
        self._ip_file = None

    def _resolve_binary(self) -> Optional[str]:
        return shutil.which(self.binary_path or "srtla_send")

    async def start(self) -> bool:
        binary = self._resolve_binary()
        if not binary:
            return False
        interfaces = [i for i in detect_interfaces()
                      if not self.interfaces or i["interface"] in self.interfaces]
        if not interfaces:
            return False
        # Upstream srtla_send expects a file of source IPs, not interface names.
        with tempfile.NamedTemporaryFile(mode="w", prefix="ratonet-srtla-", delete=False) as f:
            f.write("\n".join(i["ip"] for i in interfaces) + "\n")
            self._ip_file = Path(f.name)
        try:
            await self._launch()
        except Exception:
            self._ip_file.unlink(missing_ok=True)
            raise
        self._task = asyncio.create_task(self._monitor())
        return True

    async def _launch(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            self._resolve_binary(), str(self.listen_port), self.server_host,
            str(self.server_port), str(self._ip_file),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )

    async def _monitor(self) -> None:
        while True:
            code = await self._process.wait()
            log.warning("SRTLA sender terminou (%d); reiniciando", code)
            await asyncio.sleep(3)
            await self._launch()

    def get_primary_srt_url(self) -> str:
        return f"srt://127.0.0.1:{self.listen_port}?mode=caller"

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
        if self._ip_file:
            self._ip_file.unlink(missing_ok=True)
            self._ip_file = None
