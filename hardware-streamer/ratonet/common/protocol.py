"""Protocolo de mensagens WebSocket entre field agent e servidor.

Todas as mensagens seguem o formato:
{
    "type": "<message_type>",
    "streamer_id": "<id>",
    "timestamp": "<ISO 8601>",
    "data": { ... }
}
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """Tipos de mensagem do protocolo."""

    GPS = "gps"
    HARDWARE = "hardware"
    NETWORK = "network"
    STARLINK = "starlink"
    HEALTH = "health"
    STREAM_STATUS = "stream_status"
    COMMAND = "command"


class ProtocolMessage(BaseModel):
    """Mensagem base do protocolo RatoNet."""

    type: MessageType
    streamer_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: Dict[str, Any]

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def create(cls, msg_type: MessageType, streamer_id: str, data: Dict[str, Any]) -> ProtocolMessage:
        return cls(type=msg_type, streamer_id=streamer_id, data=data)
