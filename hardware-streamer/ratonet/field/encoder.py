"""Gerenciamento do FFmpeg para captura de vídeo e envio via SRT.

Lança FFmpeg como subprocess assíncrono, monitora saúde do processo
e reinicia automaticamente em caso de crash.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING, List, Optional

from ratonet.common.logger import get_logger

if TYPE_CHECKING:
    from ratonet.field.bonding import NetworkBonding

log = get_logger("encoder")


class SRTEncoder:
    """Gerencia pipeline FFmpeg → SRT."""

    def __init__(
        self,
        device: str = "/dev/video0",
        bitrate: str = "4000k",
        resolution: str = "1920x1080",
        codec: str = "libx264",
        fps: int = 30,
        srt_url: Optional[str] = None,
        bonding: Optional[NetworkBonding] = None,
        latency_ms: int = 500,
        passphrase: str = "",
    ) -> None:
        self.device = device
        self.bitrate = bitrate
        self.resolution = resolution
        self.codec = codec
        self.fps = fps
        self.srt_url = srt_url
        self.bonding = bonding
        self.latency_ms = latency_ms
        self.passphrase = passphrase

        self._process: Optional[asyncio.subprocess.Process] = None
        self._running = False
        self._restart_count = 0
        self._max_restarts = 10

    def _build_command(self) -> List[str]:
        """Constrói a linha de comando do FFmpeg."""
        width, height = self.resolution.split("x")

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]

        # Input — detecta tipo de dispositivo
        if self.device.startswith("/dev/video"):
            # V4L2 (Linux — webcam, HDMI capture)
            cmd += ["-f", "v4l2", "-video_size", self.resolution, "-framerate", str(self.fps)]
            cmd += ["-i", self.device]
        elif self.device.startswith("avfoundation"):
            # macOS
            cmd += ["-f", "avfoundation", "-framerate", str(self.fps)]
            cmd += ["-i", self.device]
        elif self.device == "testsrc":
            # Fonte de teste (para desenvolvimento)
            cmd += [
                "-f", "lavfi",
                "-i", f"testsrc=size={self.resolution}:rate={self.fps}",
                "-f", "lavfi",
                "-i", f"sine=frequency=1000:sample_rate=48000",
            ]
        else:
            # Tenta como input genérico
            cmd += ["-i", self.device]

        # Encode
        cmd += [
            "-c:v", self.codec,
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-b:v", self.bitrate,
            "-maxrate", self.bitrate,
            "-bufsize", f"{int(self.bitrate.replace('k', '000')) * 2}",
            "-g", str(self.fps * 2),  # GOP = 2 segundos
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "48000",
        ]

        # Output SRT
        output_url = self._get_output_url()
        srt_params = f"latency={self.latency_ms * 1000}"
        if self.passphrase:
            srt_params += f"&passphrase={self.passphrase}"

        cmd += [
            "-f", "mpegts",
            f"srt://{output_url}?{srt_params}",
        ]

        return cmd

    def _get_output_url(self) -> str:
        """Retorna URL SRT de destino."""
        if self.srt_url:
            return self.srt_url

        if self.bonding:
            # Usa o primeiro link ativo do bonding
            url = self.bonding.get_primary_srt_url()
            if url:
                return url

        return "localhost:9000"

    async def start(self) -> None:
        """Inicia o encoder FFmpeg."""
        if not shutil.which("ffmpeg"):
            log.error("FFmpeg não encontrado no PATH!")
            return

        self._running = True
        self._restart_count = 0
        await self._launch()

        # Monitor de saúde em background
        asyncio.create_task(self._health_monitor())

    async def stop(self) -> None:
        """Para o encoder."""
        self._running = False
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None
        log.info("Encoder parado")

    async def _launch(self) -> None:
        """Lança processo FFmpeg."""
        cmd = self._build_command()
        log.info("Iniciando FFmpeg: %s", " ".join(cmd))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info("FFmpeg PID: %d", self._process.pid)

        # Log stderr em background
        asyncio.create_task(self._log_stderr())

    async def _log_stderr(self) -> None:
        """Loga stderr do FFmpeg."""
        if not self._process or not self._process.stderr:
            return
        async for line in self._process.stderr:
            text = line.decode().strip()
            if text:
                log.debug("[FFmpeg] %s", text)

    async def _health_monitor(self) -> None:
        """Monitora processo FFmpeg e reinicia se necessário."""
        while self._running:
            await asyncio.sleep(2)

            if self._process is None:
                continue

            retcode = self._process.returncode
            if retcode is not None:
                # Processo morreu
                if not self._running:
                    break

                self._restart_count += 1
                if self._restart_count > self._max_restarts:
                    log.error("FFmpeg excedeu máximo de restarts (%d)", self._max_restarts)
                    self._running = False
                    break

                log.warning(
                    "FFmpeg morreu (code %d), reiniciando (%d/%d)...",
                    retcode, self._restart_count, self._max_restarts,
                )
                await asyncio.sleep(2)
                await self._launch()

    @property
    def is_running(self) -> bool:
        """Retorna se o encoder está rodando."""
        return (
            self._running
            and self._process is not None
            and self._process.returncode is None
        )

    async def change_bitrate(self, new_bitrate: str) -> None:
        """Muda bitrate reiniciando o encoder."""
        self.bitrate = new_bitrate
        log.info("Mudando bitrate para %s, reiniciando encoder...", new_bitrate)
        if self._process:
            self._process.terminate()
            # O health_monitor vai relançar automaticamente
