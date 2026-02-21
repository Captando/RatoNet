"""Testes para relay multi-streamer e alocação de portas."""

from ratonet.server.srt_receiver import PortAllocator
from ratonet.server.relay import StreamerRelayManager


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
