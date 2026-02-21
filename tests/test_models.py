"""Testes para modelos Pydantic."""

from ratonet.dashboard.models import (
    GPSPosition,
    HardwareMetrics,
    HealthState,
    HealthStatus,
    NetworkLink,
    RegisterRequest,
    RegisterResponse,
    StreamDestination,
    Streamer,
)


def test_gps_position_defaults():
    """GPSPosition cria com defaults corretos."""
    gps = GPSPosition(lat=-23.55, lng=-46.63)
    assert gps.speed_kmh == 0.0
    assert gps.altitude_m == 0.0
    assert gps.satellites == 0
    assert gps.fix == "none"


def test_gps_position_serialization():
    """GPSPosition serializa e deserializa."""
    gps = GPSPosition(lat=-23.55, lng=-46.63, speed_kmh=80.5, heading=180.0)
    data = gps.model_dump()
    assert data["lat"] == -23.55
    assert data["speed_kmh"] == 80.5
    gps2 = GPSPosition(**data)
    assert gps2.lat == gps.lat


def test_health_status_defaults():
    """HealthStatus tem score 100 e estado HEALTHY."""
    h = HealthStatus()
    assert h.score == 100
    assert h.state == HealthState.HEALTHY


def test_streamer_model():
    """Streamer model cria com todos os campos."""
    s = Streamer(id="test-id", name="Test Streamer")
    assert s.is_live is False
    assert s.location_name == ""
    assert s.gps.lat == 0.0
    assert s.health.score == 100
    data = s.model_dump()
    assert data["id"] == "test-id"


def test_register_request():
    """RegisterRequest valida campos obrigatórios."""
    req = RegisterRequest(name="Test", email="test@example.com")
    assert req.color == "#ff6600"
    assert req.socials == []


def test_register_response():
    """RegisterResponse inclui pull_key."""
    resp = RegisterResponse(
        id="uuid", name="Test", api_key="rn_xxx", pull_key="pk_yyy", approved=True,
    )
    assert resp.pull_key == "pk_yyy"


def test_network_link():
    """NetworkLink calcula score."""
    link = NetworkLink(interface="eth0", type="ethernet", connected=True, score=85)
    assert link.score == 85
    assert link.connected is True


def test_stream_destination():
    """StreamDestination cria com defaults corretos."""
    dest = StreamDestination(platform="twitch", rtmp_url="rtmp://live.twitch.tv/app/key123")
    assert dest.platform == "twitch"
    assert dest.enabled is True
    data = dest.model_dump()
    assert data["rtmp_url"] == "rtmp://live.twitch.tv/app/key123"


def test_streamer_with_destinations():
    """Streamer aceita stream_destinations."""
    s = Streamer(
        id="test-id",
        name="Test",
        stream_destinations=[
            StreamDestination(platform="twitch", rtmp_url="rtmp://tw/key"),
            StreamDestination(platform="youtube", rtmp_url="rtmp://yt/key", enabled=False),
        ],
    )
    assert len(s.stream_destinations) == 2
    assert s.stream_destinations[1].enabled is False
