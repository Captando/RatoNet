"""Testes para o geocoder."""

from ratonet.dashboard.geocoder import _haversine, _should_update, _cache, get_cached_location
import time


def test_haversine_known_distance():
    """Haversine entre SP e RJ ~ 361km."""
    d = _haversine(-23.55, -46.63, -22.90, -43.17)
    assert 350_000 < d < 370_000  # 350-370 km


def test_haversine_same_point():
    """Haversine de ponto para ele mesmo = 0."""
    d = _haversine(-23.55, -46.63, -23.55, -46.63)
    assert d == 0.0


def test_haversine_short_distance():
    """Haversine entre pontos próximos (< 1km)."""
    d = _haversine(-23.5500, -46.6300, -23.5510, -46.6310)
    assert d < 2000  # Menos de 2km


def test_should_update_new_streamer():
    """Deve atualizar para streamer sem cache."""
    assert _should_update("new-streamer-xyz", -23.55, -46.63) is True


def test_should_update_cached_same_position():
    """Não deve atualizar se posição não mudou e tempo < threshold."""
    _cache["test-cache-1"] = (-23.55, -46.63, time.time(), "São Paulo")
    assert _should_update("test-cache-1", -23.55, -46.63) is False
    del _cache["test-cache-1"]


def test_should_update_moved_far():
    """Deve atualizar se moveu mais de 150m."""
    _cache["test-cache-2"] = (-23.55, -46.63, time.time(), "São Paulo")
    # Move ~15km
    assert _should_update("test-cache-2", -23.65, -46.73) is True
    del _cache["test-cache-2"]


def test_should_update_time_expired():
    """Deve atualizar se mais de 5 min se passaram."""
    _cache["test-cache-3"] = (-23.55, -46.63, time.time() - 400, "São Paulo")
    assert _should_update("test-cache-3", -23.55, -46.63) is True
    del _cache["test-cache-3"]


def test_get_cached_location():
    """Retorna cache sem fazer request."""
    _cache["test-cache-4"] = (-23.55, -46.63, time.time(), "Pinheiros, São Paulo")
    assert get_cached_location("test-cache-4") == "Pinheiros, São Paulo"
    del _cache["test-cache-4"]


def test_get_cached_location_missing():
    """Retorna None se não tem cache."""
    assert get_cached_location("nonexistent-streamer") is None
