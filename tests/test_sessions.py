import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from ratonet.dashboard.models import HealthState
from ratonet.dashboard.ws_handler import ConnectionManager


@pytest.fixture
async def manager(monkeypatch):
    manager = ConnectionManager()
    monkeypatch.setattr(manager, '_update_location', AsyncMock())
    yield manager
    await manager.stop()


def profile():
    return {'id': 'streamer', 'name': 'Streamer', 'config': {}}


async def test_late_disconnect_cannot_remove_new_connection(manager):
    old, new = AsyncMock(), AsyncMock()
    await manager.connect_field(old, 'streamer', profile())
    await manager.connect_field(new, 'streamer', profile())
    await manager.disconnect_field('streamer', old)
    assert manager.field_agents['streamer'] is new
    assert 'streamer' in manager.streamers
    old.close.assert_awaited_once()


async def test_gps_session_does_not_restart_or_stop_video(manager):
    manager.streamer_relay.start_for_streamer = AsyncMock()
    manager.streamer_relay.stop_for_streamer = AsyncMock()
    field, gps = AsyncMock(), AsyncMock()
    await manager.connect_field(field, 'streamer', profile(), video=True)
    port = manager.port_allocator.get_port('streamer')
    await manager.connect_field(gps, 'streamer', profile(), source='gps')
    await manager.disconnect_field('streamer', gps, source='gps')
    manager.streamer_relay.start_for_streamer.assert_awaited_once()
    assert manager.streamer_relay.stop_for_streamer.await_count == 1  # field startup only
    assert manager.port_allocator.get_port('streamer') == port
    assert manager.field_agents['streamer'] is field


async def test_session_negotiates_private_port_and_secret(manager):
    manager.streamer_relay.start_for_streamer = AsyncMock()
    first, second = AsyncMock(), AsyncMock()
    await manager.connect_field(first, 'streamer', profile(), video=True)
    data = first.send_json.call_args.args[0]['data']['video']
    other = {'id': 'second', 'name': 'Other', 'config': {}}
    await manager.connect_field(second, 'second', other, video=True)
    other_data = second.send_json.call_args.args[0]['data']['video']
    assert data['port'] != other_data['port']
    assert data['passphrase'] != other_data['passphrase']
    assert 10 <= len(data['passphrase']) <= 79
    assert manager.streamers['streamer'].health.state == HealthState.UNKNOWN


async def test_invalid_payload_does_not_kill_session_or_spoof_health(manager):
    ws = AsyncMock()
    await manager.connect_field(ws, 'streamer', profile())
    for kind, data in [('gps', {'lat': 'bad'}), ('network', {'links': [None]}),
                       ('health', {'score': 100, 'state': 'healthy'})]:
        await manager.handle_field_message('streamer', json.dumps({
            'type': kind, 'streamer_id': 'streamer', 'data': data}), ws)
    assert manager.field_agents['streamer'] is ws
    assert manager.streamers['streamer'].health.state == HealthState.UNKNOWN


async def test_late_messages_from_replaced_session_are_ignored(manager):
    old, new = AsyncMock(), AsyncMock()
    await manager.connect_field(old, 'streamer', profile())
    await manager.connect_field(new, 'streamer', profile())
    await manager.handle_field_message('streamer', json.dumps({
        'type': 'hardware', 'streamer_id': 'streamer', 'data': {'cpu_percent': 99}}), old)
    assert manager.streamers['streamer'].hardware.cpu_percent == 0


async def test_video_failure_releases_capacity(manager):
    manager.streamer_relay.start_for_streamer = AsyncMock(side_effect=RuntimeError('failed'))
    ws = AsyncMock()
    with pytest.raises(RuntimeError):
        await manager.connect_field(ws, 'streamer', profile(), video=True)
    assert manager.port_allocator.get_port('streamer') is None
    assert 'streamer' not in manager.field_agents


async def test_gps_only_presence_expires(manager):
    from datetime import datetime, timezone, timedelta
    from ratonet.config import settings
    manager.ensure_streamer(profile()).updated_at = datetime.now(timezone.utc) - timedelta(seconds=31)
    old = settings.health.check_interval_s
    settings.health.check_interval_s = 0.01
    try:
        task = asyncio.create_task(manager._maintenance())
        await asyncio.sleep(0.03)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert not manager.streamers
    finally:
        settings.health.check_interval_s = old
