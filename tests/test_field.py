from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock
import pytest

from ratonet.field.bonding import SRTLASender
from ratonet.field.encoder import SRTEncoder
from ratonet.field.main import FieldAgent


@pytest.mark.parametrize('url', ['vps.example:9012', 'srt://vps.example:9012?mode=caller'])
def test_encoder_url_has_one_protocol_and_query(url):
    output = SRTEncoder(srt_url=url, passphrase='test-secret-123', latency_ms=750)._build_command()[-1]
    parsed = urlsplit(output)
    assert parsed.hostname == 'vps.example'
    assert parsed.port == 9012
    assert output.count('srt://') == 1
    assert output.count('?') == 1
    assert parse_qs(parsed.query)['latency'] == ['750000']
    assert parse_qs(parsed.query)['passphrase'] == ['test-secret-123']


def test_srtla_url_is_not_double_prefixed():
    sender = SRTLASender(5000, 'vps.example', 9013)
    output = SRTEncoder(bonding=sender)._build_command()[-1]
    assert urlsplit(output).hostname == '127.0.0.1'
    assert output.count('srt://') == 1


async def test_agent_uses_negotiated_port_and_hostname(monkeypatch):
    monkeypatch.setattr(SRTEncoder, 'start', AsyncMock())
    agent = FieldAgent('id', 'wss://vps.example/ws/field', enable_video=True)
    await agent._start_video({'transport': 'srt', 'port': 9012, 'passphrase': 'private-token', 'latency_ms': 500})
    parsed = urlsplit(agent._encoder._build_command()[-1])
    assert parsed.hostname == 'vps.example'
    assert parsed.port == 9012


def test_no_silent_localhost_video_fallback():
    with pytest.raises(ValueError, match='negociado'):
        SRTEncoder()._build_command()


def test_field_bundle_contains_canonical_sources_and_no_secrets(tmp_path):
    import tarfile
    from pathlib import Path
    from scripts.build_field_bundle import build
    target = tmp_path / 'field.tar.gz'
    build(target)
    with tarfile.open(target) as archive:
        code = archive.extractfile('ratonet-field/ratonet/field/main.py').read()
        assert code == Path('ratonet/field/main.py').read_bytes()
        assert not any(name.endswith('/.env') or '/dashboard/' in name for name in archive.getnames())


async def test_srtla_uses_source_ip_file_and_cleans_up(monkeypatch):
    import asyncio
    from pathlib import Path
    from ratonet.field import bonding
    monkeypatch.setattr(bonding, 'detect_interfaces', lambda: [
        {'interface': 'wwan0', 'ip': '192.0.2.1'}, {'interface': 'eth0', 'ip': '192.0.2.2'}])
    sender = SRTLASender(5000, 'vps.example', 9001, interfaces=['wwan0'])
    monkeypatch.setattr(sender, '_resolve_binary', lambda: '/test/srtla_send')
    process = AsyncMock()
    process.returncode = None
    process.terminate = lambda: setattr(process, 'returncode', 0)
    process.kill = process.terminate
    stopped = asyncio.Event()
    async def wait():
        await stopped.wait()
        return 0
    process.wait = wait
    original_terminate = process.terminate
    def terminate():
        original_terminate()
        stopped.set()
    process.terminate = terminate
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(bonding.asyncio, 'create_subprocess_exec', spawn)
    assert await sender.start()
    args = spawn.call_args.args
    ip_file = Path(args[-1])
    assert len(args) == 5
    assert ip_file.read_text() == '192.0.2.1\n'
    await sender.stop()
    assert not ip_file.exists()
