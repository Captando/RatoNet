"""Reverse geocoding via Nominatim (OpenStreetMap) com cache em memória."""

from __future__ import annotations

import math
import time
from typing import Dict, Optional, Tuple

from ratonet.common.logger import get_logger

log = get_logger("geocoder")

# Cache: streamer_id → (lat, lng, timestamp, location_name)
_cache: Dict[str, Tuple[float, float, float, str]] = {}

# Re-query se moveu mais de 150m ou mais de 5 minutos
_DISTANCE_THRESHOLD_M = 150.0
_TIME_THRESHOLD_S = 300.0

# Nominatim user-agent (obrigatório)
_USER_AGENT = "RatoNet/1.0 (https://github.com/Captando/RatoNet)"


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distância em metros entre dois pontos (fórmula de Haversine)."""
    R = 6371000  # raio da Terra em metros
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _should_update(streamer_id: str, lat: float, lng: float) -> bool:
    """Verifica se deve re-consultar o geocoder."""
    if streamer_id not in _cache:
        return True

    cached_lat, cached_lng, cached_time, _ = _cache[streamer_id]
    elapsed = time.time() - cached_time
    distance = _haversine(cached_lat, cached_lng, lat, lng)

    return distance > _DISTANCE_THRESHOLD_M or elapsed > _TIME_THRESHOLD_S


async def reverse_geocode(streamer_id: str, lat: float, lng: float) -> Optional[str]:
    """Retorna nome do local (bairro/cidade) para coordenadas GPS.

    Usa Nominatim (OpenStreetMap) com cache inteligente.
    Retorna None se falhar (sem erro — silencioso).
    """
    if lat == 0.0 and lng == 0.0:
        return None

    if not _should_update(streamer_id, lat, lng):
        return _cache[streamer_id][3]

    try:
        import urllib.request
        import json

        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?lat={lat}&lon={lng}&format=json&zoom=14&addressdetails=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        address = data.get("address", {})
        parts = []
        # Tenta bairro → cidade → estado
        for key in ("suburb", "neighbourhood", "city_district"):
            if key in address:
                parts.append(address[key])
                break
        for key in ("city", "town", "village", "municipality"):
            if key in address:
                parts.append(address[key])
                break
        if "state" in address:
            parts.append(address["state"])

        location_name = ", ".join(parts) if parts else data.get("display_name", "")

        _cache[streamer_id] = (lat, lng, time.time(), location_name)
        log.debug("Geocode %s: %s", streamer_id[:8], location_name)
        return location_name

    except Exception as e:
        log.debug("Geocode falhou para %s: %s", streamer_id[:8], e)
        # Retorna cache antigo se existir
        if streamer_id in _cache:
            return _cache[streamer_id][3]
        return None


def get_cached_location(streamer_id: str) -> Optional[str]:
    """Retorna localização em cache sem fazer request."""
    if streamer_id in _cache:
        return _cache[streamer_id][3]
    return None
