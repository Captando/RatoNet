"""Testes para configuração centralizada."""

from ratonet.config import Settings


def test_default_settings():
    """Settings carregam com valores padrão."""
    s = Settings()
    assert s.dashboard.port == 8000
    assert s.srt.base_port == 9000
    assert s.srt.max_links == 4
    assert s.srtla.enabled is False
    assert s.health.threshold_degraded == 70
    assert s.database.auto_approve is False


def test_srtla_config_defaults():
    """SRTLA config tem defaults corretos."""
    s = Settings()
    assert s.srtla.send_port == 5000
    assert s.srtla.rec_port == 5001
    assert s.srtla.binary_path == ""


def test_field_config_defaults():
    """Field config tem defaults corretos."""
    s = Settings()
    assert s.field.telemetry_interval_s == 1.0
    assert s.field.gps_device == "localhost:2947"
    assert s.field.video_codec == "libx264"
