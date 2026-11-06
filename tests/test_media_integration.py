"""Real SRT -> FFmpeg -> two local RTMP receivers, opt-in on Linux/CI."""

import asyncio
import json
import os
import shutil
import socket
from unittest.mock import AsyncMock

import pytest

from ratonet.config import settings
from ratonet.dashboard.models import HealthState
from ratonet.dashboard.ws_handler import ConnectionManager
from ratonet.field.main import FieldAgent

pytestmark = pytest.mark.skipif(os.environ.get('RATONET_MEDIA_TEST') != '1',
                                reason='Set RATONET_MEDIA_TEST=1 with SRT-enabled FFmpeg')


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def wait_listener(process, port):
    for _ in range(100):
        if process.returncode is not None:
            _, err = await process.communicate()
            raise AssertionError(err.decode())
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                return
        await asyncio.sleep(0.05)
    raise AssertionError('RTMP receiver did not start')


@pytest.mark.parametrize('unavailable_destination', [False, True])
async def test_negotiated_video_reaches_two_rtmp_destinations(tmp_path, monkeypatch, unavailable_destination):
    assert shutil.which('ffmpeg') and shutil.which('ffprobe')
    monkeypatch.setattr(settings.field, 'video_device', 'testsrc')
    monkeypatch.setattr(settings.field, 'video_resolution', '320x240')
    monkeypatch.setattr(settings.field, 'video_bitrate', '300k')
    manager = ConnectionManager()
    manager.port_allocator.base_port = free_port(socket.SOCK_DGRAM)
    manager.port_allocator.max_streamers = 1
    receivers = []
    files = []
    destinations = []
    agent = FieldAgent('media-test', 'ws://127.0.0.1/ws/field', enable_video=True)
    try:
        for index in range(2):
            port = free_port()
            url = f'rtmp://127.0.0.1:{port}/live/test'
            output = tmp_path / f'destination-{index}.flv'
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-listen', '1',
                '-i', url, '-c', 'copy', '-t', '6', '-y', str(output),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            receivers.append(process)
            await wait_listener(process, port)
            files.append(output)
            destinations.append({'platform': 'custom', 'rtmp_url': url})
        if unavailable_destination:
            destinations.append({'platform': 'custom', 'rtmp_url': f'rtmp://127.0.0.1:{free_port()}/live/offline'})
        ws = AsyncMock()
        await manager.connect_field(ws, 'media-test', {
            'id': 'media-test', 'name': 'Media test', 'config': {'stream_destinations': destinations}}, video=True)
        config = ws.send_json.call_args.args[0]['data']['video']
        await agent._start_video(config)
        relay = manager.streamer_relay.relays['media-test']
        async def receive_video():
            while relay.health().state != HealthState.HEALTHY:
                await asyncio.sleep(0.1)
            return await asyncio.gather(*(p.communicate() for p in receivers))
        results = await asyncio.wait_for(receive_video(), 40)
        for process, (_, err), output in zip(receivers, results, files):
            assert process.returncode == 0, err.decode()
            probe = await asyncio.create_subprocess_exec(
                'ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-of', 'json', str(output),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            data, err = await probe.communicate()
            assert probe.returncode == 0, err.decode()
            streams = json.loads(data)['streams']
            video = next(s for s in streams if s['codec_type'] == 'video')
            assert video['codec_name'] == 'h264'
            assert int(video['nb_read_frames']) > 30
            assert any(s['codec_name'] == 'aac' for s in streams)
        await agent._stop_video()
        await asyncio.sleep(6)
        assert relay.health().state == HealthState.DOWN
        await manager.disconnect_field('media-test', ws)
        assert manager.port_allocator.get_port('media-test') is None
    finally:
        await agent._stop_video()
        await manager.stop()
        for process in receivers:
            if process.returncode is None:
                process.kill()
            await process.communicate()
