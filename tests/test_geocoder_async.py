import asyncio
import time

import httpx

from ratonet.dashboard import geocoder


async def test_slow_geocoder_does_not_block_other_tasks(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={'address': {'city': 'Test City'}})

    factory = httpx.AsyncClient
    monkeypatch.setattr(geocoder, '_request_lock', asyncio.Lock())
    monkeypatch.setattr(geocoder, '_last_request', 0)
    monkeypatch.setattr(geocoder.httpx, 'AsyncClient', lambda **kw: factory(transport=httpx.MockTransport(handler), **kw))
    task = asyncio.create_task(geocoder.reverse_geocode('async-test', 1, 2))
    await asyncio.wait_for(entered.wait(), 1)
    # The HTTP response is still waiting, while the caller can keep making progress.
    assert not task.done()
    release.set()
    assert await asyncio.wait_for(task, 1) == 'Test City'
    geocoder._cache.pop('async-test', None)


async def test_requests_are_globally_spaced(monkeypatch):
    times = []

    async def handler(request):
        times.append(time.monotonic())
        return httpx.Response(200, json={'address': {'city': 'Test'}})

    factory = httpx.AsyncClient
    monkeypatch.setattr(geocoder, '_request_lock', asyncio.Lock())
    monkeypatch.setattr(geocoder, '_last_request', 0)
    monkeypatch.setattr(geocoder.httpx, 'AsyncClient', lambda **kw: factory(transport=httpx.MockTransport(handler), **kw))
    await asyncio.gather(geocoder.reverse_geocode('rate-a', 1, 2), geocoder.reverse_geocode('rate-b', 3, 4))
    assert times[1] - times[0] >= 1
    geocoder._cache.pop('rate-a', None)
    geocoder._cache.pop('rate-b', None)
