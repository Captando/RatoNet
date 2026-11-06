"""Testes para relay multi-streamer e alocação de portas."""

from ratonet.server.srt_receiver import PortAllocator
from ratonet.server.relay import StreamerRelayManager
import pytest


def test_port_allocator_sequential():
    """Aloca portas sequenciais para streamers diferentes."""
    alloc = PortAllocator(base_port=9000, ports_per_streamer=4)
    p1 = alloc.allocate("streamer-1")
    p2 = alloc.allocate("streamer-2")
    assert p1 == 9000
    assert p2 == 9004


def test_port_allocator_idempotent():
    """Mesma porta para mesmo streamer."""
    alloc = PortAllocator(base_port=9000, ports_per_streamer=4)
    p1 = alloc.allocate("streamer-1")
    p2 = alloc.allocate("streamer-1")
    assert p1 == p2 == 9000


def test_port_allocator_release():
    """Release remove alocação."""
    alloc = PortAllocator(base_port=9000, ports_per_streamer=4)
    alloc.allocate("streamer-1")
    alloc.release("streamer-1")
    assert alloc.get_port("streamer-1") is None


def test_port_allocator_get_port():
    """get_port retorna None se não alocado."""
    alloc = PortAllocator()
    assert alloc.get_port("nonexistent") is None
    alloc.allocate("test")
    assert alloc.get_port("test") is not None


def test_streamer_relay_manager_init():
    """StreamerRelayManager inicia vazio."""
    mgr = StreamerRelayManager()
    assert mgr.relays == {}
    status = mgr.get_status()
    assert status["total_streamers"] == 0


def test_mask_rtmp_url():
    """Testa mascaramento de URLs RTMP."""
    from ratonet.dashboard.routes import _mask_rtmp_url
    assert "***" in _mask_rtmp_url("rtmp://live.twitch.tv/app/live_123456789")
    assert _mask_rtmp_url("rtmp://live.twitch.tv/app/live_123456789").startswith("rtmp://live.twitch.tv/app/live")
    # URL curta não mascara
    assert _mask_rtmp_url("rtmp://x/ab") == "rtmp://x/ab"


def test_ports_are_reused_and_capacity_is_bounded():
    allocator = PortAllocator(max_streamers=2)
    for _ in range(100):
        assert allocator.allocate('reconnecting') == 9000
        allocator.release('reconnecting')
    allocator.allocate('a')
    allocator.allocate('b')
    with pytest.raises(RuntimeError, match='Capacidade'):
        allocator.allocate('c')
    allocator.release('a')
    assert allocator.allocate('c') == 9000


def test_multistream_uses_one_input():
    from ratonet.server.relay import RTMPRelay
    relay = RTMPRelay('test', ['rtmp://one/live/key', 'rtmp://two/live/key'], 'srt://0.0.0.0:9000')
    cmd = relay._build_command()
    assert cmd.count('-i') == 1
    assert 'rtmp://one/live/key' in cmd[-1]
    assert 'rtmp://two/live/key' in cmd[-1]


def test_health_requires_recent_real_frames():
    import time
    from types import SimpleNamespace
    from ratonet.server.relay import RTMPRelay
    from ratonet.dashboard.models import HealthState
    relay = RTMPRelay('test', [], 'srt://localhost:9000')
    relay._process = SimpleNamespace(returncode=None)
    relay.started_at = time.monotonic()
    assert relay.health().state == HealthState.UNKNOWN
    relay.last_frame_at = time.monotonic()
    assert relay.health().state == HealthState.HEALTHY
    relay.last_frame_at -= 6
    assert relay.health().state == HealthState.DOWN
