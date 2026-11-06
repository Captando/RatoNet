"""Testes para endpoints REST."""

import os
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient

from ratonet.dashboard.main import app
from ratonet.dashboard import db
from ratonet.config import settings
from ratonet.dashboard.ws_handler import manager
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone


@pytest.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    """Configura banco temporário para cada teste."""
    db_path = str(tmp_path / "test.db")
    settings.database.path = db_path
    await db.init_db(db_path)
    monkeypatch.setattr(manager, '_update_location', AsyncMock())
    yield
    await manager.stop()
    settings.database.path = "ratonet.db"
    settings.database.auto_approve = False
    settings.admin.token = ""


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


@pytest.mark.asyncio
async def test_destinations_full(client):
    """GET /api/me/destinations/full retorna URLs sem mascarar."""
    settings.database.auto_approve = True
    resp = await client.post("/api/register", json={"name": "Full", "email": "full@test.com"})
    api_key = resp.json()["api_key"]

    # Configura destino
    await client.put(
        f"/api/me/destinations?api_key={api_key}",
        json=[{"platform": "twitch", "rtmp_url": "rtmp://live.twitch.tv/app/live_SECRETKEY123", "enabled": True}],
    )

    # Full retorna URL completa (sem mascarar)
    resp = await client.get(f"/api/me/destinations/full?api_key={api_key}")
    assert resp.status_code == 200
    dests = resp.json()["destinations"]
    assert "SECRETKEY123" in dests[0]["rtmp_url"]

    settings.database.auto_approve = False


@pytest.mark.asyncio
async def test_livepix_crud(client):
    """Fluxo LivePix: salvar e ler token."""
    settings.database.auto_approve = True
    resp = await client.post("/api/register", json={"name": "LP", "email": "lp@test.com"})
    api_key = resp.json()["api_key"]

    # Sem token inicialmente
    resp = await client.get(f"/api/me/livepix?api_key={api_key}")
    assert resp.status_code == 200
    assert resp.json()["token"] == ""

    # Salva token
    resp = await client.put(
        f"/api/me/livepix?api_key={api_key}",
        json={"token": "my_livepix_token_123"},
    )
    assert resp.status_code == 200

    # Le token
    resp = await client.get(f"/api/me/livepix?api_key={api_key}")
    assert resp.json()["token"] == "my_livepix_token_123"

    settings.database.auto_approve = False


@pytest.mark.asyncio
async def test_admin_stats(client):
    """GET /api/admin/stats retorna estatisticas."""
    settings.admin.token = "test_admin_token"
    settings.database.auto_approve = True

    await client.post("/api/register", json={"name": "Stats", "email": "stats@test.com"})

    resp = await client.get(
        "/api/admin/stats",
        headers={"Authorization": "Bearer test_admin_token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["registered"] == 1
    assert "online_streamers" in data

    settings.admin.token = ""
    settings.database.auto_approve = False


async def test_public_profile_contains_no_secrets(client):
    s = await db.create_streamer('Public', 'secret@example.com', auto_approve=True, db_path=settings.database.path)
    await db.update_streamer(s['id'], db_path=settings.database.path, config={
        'stream_destinations': [{'rtmp_url': 'rtmp://example.com/live/secret'}], 'livepix_token': 'secret-token'})
    response = await client.get(f"/api/streamers/{s['id']}")
    assert response.status_code == 200
    assert {'email', 'api_key', 'pull_key', 'config'}.isdisjoint(response.json())
    assert 'secret' not in response.text


@pytest.mark.parametrize('path', ['%2e%2e/%2e%2e/pyproject.toml', '%2e%2e/%2e%2e/.env', '%2e%2e/%2e%2e/ratonet.db'])
async def test_pwa_cannot_escape_static_directory(client, path):
    response = await client.get('/pwa/' + path)
    assert response.status_code == 404


async def test_pwa_shell_and_worker_are_served_in_same_scope(client):
    for path in ('/pwa/', '/pwa/tracker.html', '/pwa/sw.js', '/pwa/queue.js'):
        assert (await client.get(path)).status_code == 200


async def test_pending_streamer_cannot_push_gps(client):
    s = await db.create_streamer('Pending', 'pending@example.com', db_path=settings.database.path)
    response = await client.post('/api/location', params={'streamer_id': s['id'], 'api_key': s['api_key']}, json={'lat': 1, 'lng': 2})
    assert response.status_code == 403
    assert s['id'] not in manager.streamers


async def test_gps_replay_cannot_move_live_location_backwards(client):
    s = await db.create_streamer('GPS', 'gps@example.com', auto_approve=True, db_path=settings.database.path)
    params = {'streamer_id': s['id'], 'api_key': s['api_key']}
    now = datetime.now(timezone.utc)
    response = await client.post('/api/location', params=params, json={'lat': 1, 'lng': 2, 'recorded_at': now.isoformat()})
    assert response.json()['accepted'] is True
    for age in (10, 3600):
        response = await client.post('/api/location', params=params, json={
            'lat': 3, 'lng': 4, 'recorded_at': (now - timedelta(seconds=age)).isoformat()})
        assert response.json()['accepted'] is False
    assert manager.streamers[s['id']].gps.lat == 1


@pytest.mark.parametrize('url', ['/app/file.flv', 'file:///app/file', 'rtmp://example.com/key|/tmp/file', 'http://example.com'])
async def test_destination_rejects_non_rtmp_and_tee_injection(client, url):
    s = await db.create_streamer('Dest', 'dest@example.com', db_path=settings.database.path)
    response = await client.put('/api/me/destinations', params={'api_key': s['api_key']},
                                json=[{'platform': 'custom', 'rtmp_url': url}])
    assert response.status_code == 422
