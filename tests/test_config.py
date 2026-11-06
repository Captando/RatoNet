"""Testes para configuração centralizada."""

from ratonet.config import Settings
from pathlib import Path
import subprocess
import sys


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


def test_documented_env_loads_in_fresh_process(tmp_path):
    root = Path(__file__).resolve().parents[1]
    content = (root / '.env.example').read_text()
    content = content.replace('ADMIN_TOKEN=', 'ADMIN_TOKEN=local-test-token')
    content = content.replace('FIELD_NETWORK_INTERFACES=', 'FIELD_NETWORK_INTERFACES=eth0,wwan0')
    (tmp_path / '.env').write_text(content)
    check = subprocess.run([sys.executable, '-c',
        f'import sys; sys.path.insert(0, {str(root)!r}); '
        'from ratonet.config import settings; '
        'assert settings.admin.token == "local-test-token"; '
        'assert settings.field.network_interfaces == ["eth0", "wwan0"]'],
        cwd=tmp_path, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env').write_text('ADMIN_TOKEN=file-token\nFIELD_NETWORK_INTERFACES=["eth0"]\n')
    monkeypatch.setenv('ADMIN_TOKEN', 'environment-token')
    config = Settings()
    assert config.admin.token == 'environment-token'
    assert config.field.network_interfaces == ['eth0']
