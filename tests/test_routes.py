"""Testes para endpoints REST."""

import os
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient

from ratonet.dashboard.main import app
from ratonet.dashboard import db
from ratonet.config import settings


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    """Configura banco temporário para cada teste."""
    db_path = str(tmp_path / "test.db")
    settings.database.path = db_path
    await db.init_db(db_path)
    yield
    settings.database.path = "ratonet.db"


@pytest.fixture
async def client():
    """Client HTTP para testes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_status(client):
    """GET /api/status retorna contadores."""
    resp = await client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "streamers_registered" in data
    assert "streamers_online" in data


@pytest.mark.asyncio
async def test_register_and_profile(client):
    """Fluxo completo: registro → perfil."""
    # Habilita auto-approve para testes
    settings.database.auto_approve = True

    # Registro
    resp = await client.post("/api/register", json={
        "name": "Test Streamer",
        "email": "test@ratonet.com",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Streamer"
    assert data["api_key"].startswith("rn_")
    assert data["pull_key"].startswith("pk_")
    api_key = data["api_key"]

    # Perfil
    resp = await client.get(f"/api/me?api_key={api_key}")
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["name"] == "Test Streamer"
    assert "api_key" not in profile

    settings.database.auto_approve = False


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    """Registro duplicado retorna 409."""
    settings.database.auto_approve = True
    await client.post("/api/register", json={
        "name": "First", "email": "dup@test.com",
    })
    resp = await client.post("/api/register", json={
        "name": "Second", "email": "dup@test.com",
    })
    assert resp.status_code == 409
    settings.database.auto_approve = False


@pytest.mark.asyncio
async def test_invalid_api_key(client):
    """API key inválida retorna 401."""
    resp = await client.get("/api/me?api_key=invalid_key")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_streamers_list(client):
    """GET /api/streamers retorna lista."""
    resp = await client.get("/api/streamers")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_health(client):
    """GET /api/health retorna dict."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


@pytest.mark.asyncio
async def test_destinations_crud(client):
    """Fluxo completo: registro → set destinations → get destinations."""
    settings.database.auto_approve = True

    # Registro
    resp = await client.post("/api/register", json={
        "name": "Relay Streamer", "email": "relay@test.com",
    })
    api_key = resp.json()["api_key"]

    # Inicialmente sem destinos
    resp = await client.get(f"/api/me/destinations?api_key={api_key}")
    assert resp.status_code == 200
    assert resp.json()["destinations"] == []

    # Configura destinos
    resp = await client.put(
        f"/api/me/destinations?api_key={api_key}",
        json=[
            {"platform": "twitch", "rtmp_url": "rtmp://live.twitch.tv/app/live_123456789", "enabled": True},
            {"platform": "youtube", "rtmp_url": "rtmp://a.rtmp.youtube.com/live2/abcd-efgh", "enabled": False},
        ],
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    # Verifica destinos (URLs mascaradas)
    resp = await client.get(f"/api/me/destinations?api_key={api_key}")
    assert resp.status_code == 200
    dests = resp.json()["destinations"]
    assert len(dests) == 2
    assert dests[0]["platform"] == "twitch"
    assert "***" in dests[0]["rtmp_url"]  # URL mascarada
    assert dests[1]["enabled"] is False

    settings.database.auto_approve = False


@pytest.mark.asyncio
async def test_destinations_invalid_key(client):
    """Destinos com API key inválida retorna 401."""
    resp = await client.get("/api/me/destinations?api_key=invalid")
    assert resp.status_code == 401
