"""Controle do OBS Studio via obs-websocket para fallback automático.

Quando a stream de campo degrada ou cai, troca automaticamente
para uma cena de BRB/Reconectando. Quando recupera, volta para o campo.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from ratonet.common.logger import get_logger
from ratonet.config import settings
from ratonet.server.health import StreamState

log = get_logger("obs")


class OBSController:
    """Controla OBS Studio via WebSocket."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 4455,
        password: str = "",
        scene_live: str = "LIVE",
        scene_brb: str = "BRB",
        fallback_delay: float = 3.0,
        recovery_delay: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.scene_live = scene_live
        self.scene_brb = scene_brb
        self.fallback_delay = fallback_delay
        self.recovery_delay = recovery_delay

        self._client = None
        self._connected = False
        self._current_scene: Optional[str] = None
        self._in_fallback = False
        self._fallback_timer: Optional[asyncio.Task] = None
        self._recovery_timer: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        """Conecta ao OBS via WebSocket."""
        try:
            import obsws_python as obs

            self._client = obs.ReqClient(
                host=self.host,
                port=self.port,
                password=self.password,
                timeout=5,
            )
            self._connected = True

            # Verifica cena atual
            resp = self._client.get_current_program_scene()
            self._current_scene = resp.scene_name
            log.info(
                "OBS conectado (%s:%d) — cena atual: %s",
                self.host, self.port, self._current_scene,
            )
            return True

        except ImportError:
            log.warning("obsws-python não instalado — OBS controller desabilitado")
            return False
        except Exception as e:
            log.warning("Falha ao conectar OBS (%s:%d): %s", self.host, self.port, e)
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Desconecta do OBS."""
        if self._client:
            try:
                self._client.base_client.ws.close()
            except Exception:
                pass
            self._client = None
        self._connected = False
        log.info("OBS desconectado")

    async def on_state_change(
        self,
        streamer_id: str,
        old_state: StreamState,
        new_state: StreamState,
        score: int,
    ) -> None:
        """Callback chamado pelo HealthMonitor quando o estado muda."""
        if not self._connected:
            return

        log.info(
            "[%s] OBS: estado %s → %s (score: %d)",
            streamer_id, old_state.value, new_state.value, score,
        )

        if new_state in (StreamState.CRITICAL, StreamState.DOWN):
            # Cancela recovery se estiver pendente
            if self._recovery_timer:
                self._recovery_timer.cancel()
                self._recovery_timer = None

            # Inicia fallback com delay (evita flip-flop)
            if not self._in_fallback and not self._fallback_timer:
                self._fallback_timer = asyncio.create_task(
                    self._delayed_fallback(streamer_id)
                )

        elif new_state in (StreamState.HEALTHY, StreamState.DEGRADED):
            # Cancela fallback pendente
            if self._fallback_timer:
                self._fallback_timer.cancel()
                self._fallback_timer = None

            # Inicia recovery com delay (garante que está estável)
            if self._in_fallback and not self._recovery_timer:
                self._recovery_timer = asyncio.create_task(
                    self._delayed_recovery(streamer_id)
                )

    async def _delayed_fallback(self, streamer_id: str) -> None:
        """Executa fallback após delay (evita ações prematuras)."""
        try:
            log.warning(
                "[%s] Fallback em %.1fs...", streamer_id, self.fallback_delay
            )
            await asyncio.sleep(self.fallback_delay)

            if self._connected and self._client:
                self._switch_scene(self.scene_brb)
                self._in_fallback = True
                log.warning("[%s] FALLBACK ATIVADO → cena '%s'", streamer_id, self.scene_brb)

        except asyncio.CancelledError:
            log.info("[%s] Fallback cancelado (stream recuperou a tempo)", streamer_id)
        finally:
            self._fallback_timer = None

    async def _delayed_recovery(self, streamer_id: str) -> None:
        """Executa recovery após delay (garante estabilidade)."""
        try:
            log.info(
                "[%s] Recovery em %.1fs...", streamer_id, self.recovery_delay
            )
            await asyncio.sleep(self.recovery_delay)

            if self._connected and self._client:
                self._switch_scene(self.scene_live)
                self._in_fallback = False
                log.info("[%s] RECOVERY → cena '%s'", streamer_id, self.scene_live)

        except asyncio.CancelledError:
            log.info("[%s] Recovery cancelado (stream degradou novamente)", streamer_id)
        finally:
            self._recovery_timer = None

    def _switch_scene(self, scene_name: str) -> None:
        """Troca cena no OBS."""
        if not self._client:
            return
        try:
            self._client.set_current_program_scene(scene_name)
            self._current_scene = scene_name
        except Exception as e:
            log.error("Erro ao trocar cena para '%s': %s", scene_name, e)

    def set_source_visible(self, scene: str, source: str, visible: bool) -> None:
        """Mostra/esconde uma source em uma cena (útil para overlays)."""
        if not self._client:
            return
        try:
            scene_item_id = self._client.get_scene_item_id(scene, source).scene_item_id
            self._client.set_scene_item_enabled(scene, scene_item_id, visible)
        except Exception as e:
            log.warning("Erro ao alterar visibilidade de '%s': %s", source, e)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_in_fallback(self) -> bool:
        return self._in_fallback

    def get_status(self) -> dict:
        """Status do controller OBS."""
        return {
            "connected": self._connected,
            "current_scene": self._current_scene,
            "in_fallback": self._in_fallback,
        }

    @classmethod
    def from_config(cls) -> OBSController:
        """Cria OBSController a partir da configuração."""
        return cls(
            host=settings.obs.host,
            port=settings.obs.port,
            password=settings.obs.password,
            scene_live=settings.obs.scene_live,
            scene_brb=settings.obs.scene_brb,
            fallback_delay=settings.obs.fallback_delay_s,
            recovery_delay=settings.obs.recovery_delay_s,
        )
