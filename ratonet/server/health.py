"""Monitor de saúde da stream com state machine.

Estados: HEALTHY → DEGRADED → CRITICAL → DOWN
Aciona OBS controller quando necessário.
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

from ratonet.common.logger import get_logger
from ratonet.config import settings

log = get_logger("health")


class StreamState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    DOWN = "down"


class HealthMonitor:
    """Monitora saúde da stream e gerencia transições de estado."""

    def __init__(
        self,
        streamer_id: str,
        threshold_degraded: int = 70,
        threshold_critical: int = 40,
        threshold_down: int = 10,
        check_interval: float = 2.0,
        on_state_change: Optional[Callable] = None,
    ) -> None:
        self.streamer_id = streamer_id
        self.threshold_degraded = threshold_degraded
        self.threshold_critical = threshold_critical
        self.threshold_down = threshold_down
        self.check_interval = check_interval
        self.on_state_change = on_state_change

        self.state = StreamState.DOWN
        self.score = 0
        self.last_update = 0.0
        self._running = False

        # Métricas agregadas
        self.active_links = 0
        self.total_links = 0
        self.bitrate_kbps = 0.0
        self.rtt_avg_ms = 0.0
        self.packet_loss_avg = 0.0

        # Histórico para suavizar (evitar flip-flop)
        self._score_history: list = []
        self._history_size = 5

    def update_metrics(
        self,
        active_links: int = 0,
        total_links: int = 0,
        bitrate_kbps: float = 0.0,
        rtt_avg_ms: float = 0.0,
        packet_loss_avg: float = 0.0,
        link_scores: Optional[list] = None,
    ) -> None:
        """Atualiza métricas e recalcula score."""
        self.active_links = active_links
        self.total_links = total_links
        self.bitrate_kbps = bitrate_kbps
        self.rtt_avg_ms = rtt_avg_ms
        self.packet_loss_avg = packet_loss_avg
        self.last_update = time.time()

        # Calcula score composto
        self.score = self._calculate_score(link_scores)

        # Suaviza com histórico
        self._score_history.append(self.score)
        if len(self._score_history) > self._history_size:
            self._score_history.pop(0)

        smoothed = sum(self._score_history) // len(self._score_history)
        self.score = smoothed

        # Avalia transição de estado
        old_state = self.state
        self.state = self._evaluate_state(self.score)

        if old_state != self.state:
            log.info(
                "[%s] Estado: %s → %s (score: %d)",
                self.streamer_id, old_state.value, self.state.value, self.score,
            )
            if self.on_state_change:
                asyncio.create_task(
                    self._notify_state_change(old_state, self.state)
                )

    def _calculate_score(self, link_scores: Optional[list] = None) -> int:
        """Calcula score composto de saúde (0-100)."""
        if self.active_links == 0:
            return 0

        score = 100

        # Fator: links ativos vs total
        if self.total_links > 0:
            link_ratio = self.active_links / self.total_links
            if link_ratio < 0.5:
                score -= 30
            elif link_ratio < 1.0:
                score -= 10

        # Fator: bitrate (esperado ~4000kbps)
        if self.bitrate_kbps < 1000:
            score -= 30
        elif self.bitrate_kbps < 2000:
            score -= 15

        # Fator: RTT médio
        if self.rtt_avg_ms > 200:
            score -= 20
        elif self.rtt_avg_ms > 100:
            score -= 10

        # Fator: packet loss
        if self.packet_loss_avg > 5:
            score -= 25
        elif self.packet_loss_avg > 1:
            score -= 10

        # Fator: melhor score individual dos links
        if link_scores:
            best = max(link_scores)
            if best < 50:
                score -= 15

        # Fator: tempo desde último update
        staleness = time.time() - self.last_update
        if staleness > 10:
            score -= 30
        elif staleness > 5:
            score -= 15

        return max(0, min(100, score))

    def _evaluate_state(self, score: int) -> StreamState:
        """Avalia estado baseado no score."""
        if score <= self.threshold_down:
            return StreamState.DOWN
        elif score <= self.threshold_critical:
            return StreamState.CRITICAL
        elif score <= self.threshold_degraded:
            return StreamState.DEGRADED
        else:
            return StreamState.HEALTHY

    async def _notify_state_change(
        self, old_state: StreamState, new_state: StreamState
    ) -> None:
        """Notifica callback de mudança de estado."""
        try:
            if asyncio.iscoroutinefunction(self.on_state_change):
                await self.on_state_change(self.streamer_id, old_state, new_state, self.score)
            else:
                self.on_state_change(self.streamer_id, old_state, new_state, self.score)
        except Exception as e:
            log.error("Erro no callback de estado: %s", e)

    def get_status(self) -> Dict[str, Any]:
        """Retorna status atual de saúde."""
        return {
            "score": self.score,
            "state": self.state.value,
            "active_links": self.active_links,
            "total_links": self.total_links,
            "bitrate_kbps": self.bitrate_kbps,
            "message": self._status_message(),
        }

    def _status_message(self) -> str:
        """Mensagem legível do status."""
        messages = {
            StreamState.HEALTHY: "Stream estável",
            StreamState.DEGRADED: "Qualidade degradada — monitorando",
            StreamState.CRITICAL: "Conexão crítica — fallback pode ser acionado",
            StreamState.DOWN: "Stream offline",
        }
        return messages.get(self.state, "")

    @classmethod
    def from_config(
        cls, streamer_id: str, on_state_change: Optional[Callable] = None
    ) -> HealthMonitor:
        """Cria HealthMonitor a partir da configuração."""
        return cls(
            streamer_id=streamer_id,
            threshold_degraded=settings.health.threshold_degraded,
            threshold_critical=settings.health.threshold_critical,
            threshold_down=settings.health.threshold_down,
            check_interval=settings.health.check_interval_s,
            on_state_change=on_state_change,
        )
