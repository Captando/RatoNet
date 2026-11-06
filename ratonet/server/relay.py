"""One FFmpeg input per streamer, with independent tee outputs."""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlsplit, parse_qs

from ratonet.common.logger import get_logger
from ratonet.config import settings
from ratonet.dashboard.models import HealthState, HealthStatus, StreamDestination

log = get_logger("relay")


class RTMPRelay:
    """Receives one media stream and fans it out without rebinding its input."""

    def __init__(self, name: str, destinations: List[str], input_url: str) -> None:
        self.name = name
        self.destinations = destinations
        self.input_url = input_url
        self._process: Optional[asyncio.subprocess.Process] = None
        self._task: Optional[asyncio.Task] = None
        self._error_task: Optional[asyncio.Task] = None
        self._running = False
        self._restart_count = 0
        self.last_frame_at = 0.0
        self.started_at = 0.0
        self.bitrate_kbps = 0.0

    def _build_command(self) -> List[str]:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-stats_period", "1", "-progress", "pipe:1",
            "-i", self.input_url, "-map", "0:v:0", "-map", "0:a?", "-c", "copy",
        ]
        if self.destinations:
            outputs = "|".join(f"[f=flv:onfail=ignore]{url}" for url in self.destinations)
            cmd += [
                # MPEG-TS tags are not valid FLV tags; tee/fifo preserves them unless explicit.
                "-tag:v", "7", "-tag:a", "10", "-bsf:a", "aac_adtstoasc",
                "-f", "tee", "-use_fifo", "1",
                "-fifo_options", "attempt_recovery=1:recover_any_error=1:recovery_wait_time=1:drop_pkts_on_overflow=1:restart_with_keyframe=1",
                outputs,
            ]
        else:
            # Receive-only sessions still measure real incoming video.
            cmd += ["-f", "null", "-"]
        return cmd

    async def start(self) -> None:
        if not shutil.which("ffmpeg"):
            raise RuntimeError("FFmpeg não encontrado")
        self._running = True
        self.started_at = time.monotonic()
        await self._launch()
        self._task = asyncio.create_task(self._supervise())

    async def _launch(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            *self._build_command(), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._error_task = asyncio.create_task(self._read_errors(self._process))

    async def _read_errors(self, process) -> None:
        secrets = list(self.destinations)
        secrets += [urlsplit(url).path.rsplit('/', 1)[-1] for url in self.destinations]
        secrets += parse_qs(urlsplit(self.input_url).query).get('passphrase', [])
        async for line in process.stderr:
            message = line.decode(errors='replace').strip()
            for secret in secrets:
                if secret:
                    message = message.replace(secret, '***')
            log.warning('[%s] FFmpeg: %s', self.name, message[:1000])

    async def _read_progress(self, process) -> None:
        frames = 0
        async for line in process.stdout:
            key, _, value = line.decode(errors="replace").strip().partition("=")
            if key == "frame":
                current = int(value)
                if current > frames:
                    self.last_frame_at = time.monotonic()
                    frames = current
            elif key == "bitrate" and value.endswith("kbits/s"):
                self.bitrate_kbps = float(value.removesuffix("kbits/s"))

    async def _supervise(self) -> None:
        try:
            while self._running:
                process = self._process
                await self._read_progress(process)
                code = await process.wait()
                if self._error_task:
                    await self._error_task
                if not self._running:
                    break
                self._restart_count += 1
                log.warning("[%s] FFmpeg terminou (%s); reconectando", self.name, code)
                await asyncio.sleep(min(2 ** min(self._restart_count, 4), 15))
                if self._running:
                    await self._launch()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[%s] Falha no supervisor de vídeo", self.name)
            self._running = False

    async def stop(self) -> None:
        self._running = False
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
        if self._error_task:
            await asyncio.gather(self._error_task, return_exceptions=True)
            self._error_task = None

    def health(self) -> HealthStatus:
        now = time.monotonic()
        alive = self._process is not None and self._process.returncode is None
        if not self.last_frame_at and alive and now - self.started_at < 10:
            return HealthStatus(message="Aguardando vídeo")
        age = now - self.last_frame_at if self.last_frame_at else float("inf")
        if not alive or age > 5:
            return HealthStatus(state=HealthState.DOWN, total_links=1, message="Vídeo sem frames recentes")
        degraded = age > 2.5
        return HealthStatus(
            score=60 if degraded else 100,
            state=HealthState.DEGRADED if degraded else HealthState.HEALTHY,
            active_links=1, total_links=1, bitrate_kbps=self.bitrate_kbps,
            message="Frames atrasados" if degraded else "Vídeo recebido",
        )

    def get_status(self) -> Dict[str, Any]:
        health = self.health()
        return {"name": self.name, "active": health.active_links > 0,
                "restarts": self._restart_count, "health": health.model_dump(mode="json")}


class StreamerRelayManager:
    def __init__(self) -> None:
        self.relays: Dict[str, RTMPRelay] = {}

    async def start_for_streamer(
        self, streamer_id: str, destinations: List[Dict[str, Any]], srt_port: int,
        passphrase: str, localhost: bool = False,
    ) -> None:
        await self.stop_for_streamer(streamer_id)
        validated = [StreamDestination.model_validate(d) for d in destinations]
        urls = [d.rtmp_url for d in validated if d.enabled]
        host = "127.0.0.1" if localhost else "0.0.0.0"
        params = urlencode({"mode": "listener", "latency": settings.srt.latency_ms * 1000,
                            "passphrase": passphrase, "pbkeylen": 16, "lossmaxttl": 40})
        relay = RTMPRelay(streamer_id, urls, f"srt://{host}:{srt_port}?{params}")
        await relay.start()
        self.relays[streamer_id] = relay

    async def stop_for_streamer(self, streamer_id: str) -> None:
        relay = self.relays.get(streamer_id)
        if relay:
            await relay.stop()
            self.relays.pop(streamer_id, None)

    async def stop_all(self) -> None:
        await asyncio.gather(*(self.stop_for_streamer(sid) for sid in list(self.relays)))

    def get_status(self) -> Dict[str, Any]:
        return {"total_streamers": len(self.relays),
                "streamers": {sid: relay.get_status() for sid, relay in self.relays.items()}}
