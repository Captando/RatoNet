import asyncio
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from ratonet.config import settings
from ratonet.dashboard import db
from ratonet.dashboard.main import app
from ratonet.dashboard.ws_handler import manager


def test_real_websocket_gps_and_hardware_coexist(tmp_path, monkeypatch):
    monkeypatch.setattr(settings.database, 'path', str(tmp_path / 'ws.db'))
    monkeypatch.setattr(manager, '_update_location', AsyncMock())
    with TestClient(app) as client:
        response = client.post('/api/register', json={'name': 'Socket', 'email': 'socket@example.com'})
        s = response.json()
        asyncio.run(db.approve_streamer(s['id'], db_path=settings.database.path))
        url = f"/ws/field/{s['id']}?key={s['api_key']}"
        with client.websocket_connect('/ws/dashboard') as dashboard:
            assert dashboard.receive_json()['type'] == 'full_sync'
            with client.websocket_connect(url) as field:
                assert field.receive_json()['type'] == 'session_ready'
                dashboard.receive_json()
                with client.websocket_connect(url + '&source=gps') as gps:
                    assert gps.receive_json()['data']['video'] is None
                    dashboard.receive_json()
                    field.send_json({'type': 'hardware', 'streamer_id': s['id'], 'data': {'cpu_percent': 42}})
                    update = dashboard.receive_json()['data']['streamer']
                    assert update['hardware']['cpu_percent'] == 42
                    assert update['health']['state'] == 'unknown'
                    gps.close()
                    dashboard.receive_json()
                field.send_json({'type': 'hardware', 'streamer_id': s['id'], 'data': {'cpu_percent': 43}})
                assert dashboard.receive_json()['data']['streamer']['hardware']['cpu_percent'] == 43
                field.close()
                assert dashboard.receive_json()['type'] == 'streamer_offline'
