"""Browser regressions for stored HTML injection and durable GPS delivery."""

import functools
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import pytest

playwright = pytest.importorskip('playwright.sync_api')
pytestmark = pytest.mark.skipif(os.environ.get('RATONET_BROWSER_TEST') != '1',
                                reason='Set RATONET_BROWSER_TEST=1 and install Chromium')


@pytest.fixture(scope='module')
def web_origin():
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith(('/pwa/', '/admin/', '/panel/')):
                self.path = '/static' + self.path
            super().do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(
        Handler, directory=str(Path(__file__).resolve().parents[1])))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def browser_page(web_origin):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        def block_external(route):
            if route.request.url.startswith(web_origin):
                route.continue_()
            elif 'tailwindcss' in route.request.url:
                route.fulfill(body='window.tailwind = {};', content_type='application/javascript')
            else:
                route.fulfill(body='', content_type='text/plain')
        page.route('**/*', block_external)
        yield page
        browser.close()


def test_pending_registration_is_text_in_admin(browser_page, web_origin):
    page = browser_page
    payload = '<img src=x onerror="window.__xss=1">'
    streamer = {'id': 'test-id', 'name': payload, 'email': payload,
                'avatar_url': 'x" onerror="window.__xss=1', 'color': 'red" onmouseover="window.__xss=1',
                'approved': False, 'is_live': False}
    page.route('**/api/**', lambda route: route.fulfill(json=(
        [streamer] if urlsplit(route.request.url).path == '/api/admin/streamers' else {})))
    page.goto(web_origin + '/admin/')
    page.locator('#login-token').fill('fake-admin-token')
    page.evaluate('doLogin()')
    page.evaluate("switchTab('streamers')")
    page.wait_for_function("document.getElementById('streamers-table').textContent.includes('<img')")
    assert page.locator('#streamers-table').inner_text().count(payload) == 2
    assert page.locator('#streamers-table [onerror]').count() == 0
    assert page.evaluate('window.__xss || 0') == 0


def test_profile_and_destinations_do_not_inject_attributes(browser_page, web_origin):
    page = browser_page
    payload = '"><img src=x onerror="window.__xss=1">'
    profile = {'id': 'test-id', 'name': 'Test', 'pull_key': 'pk_test', 'socials': [payload]}
    def api(route):
        path = urlsplit(route.request.url).path
        data = profile if path == '/api/me' else {}
        if path == '/api/me/destinations/full':
            data = {'destinations': [{'platform': payload, 'rtmp_url': payload, 'enabled': True}]}
        route.fulfill(json=data)
    page.route('**/api/**', api)
    page.goto(web_origin + '/panel/')
    page.locator('#login-key').fill('fake-api-key')
    page.evaluate('doLogin()')
    page.wait_for_function("document.querySelector('.dest-url') !== null")
    assert page.locator('#pf-socials input').input_value() == payload
    assert page.locator('.dest-url').input_value() == payload
    assert page.locator('#pf-socials img, #dest-list img').count() == 0
    assert page.evaluate('window.__xss || 0') == 0


def test_offline_queue_survives_reload_and_failed_retry(browser_page, web_origin):
    page = browser_page
    creds = {'serverUrl': web_origin, 'streamerId': 'gps-test', 'apiKey': 'fake-key', 'name': 'GPS'}
    page.add_init_script(f"localStorage.setItem('ratonet_creds', {json.dumps(json.dumps(creds))});")
    page.goto(web_origin + '/pwa/tracker.html')
    page.evaluate("gpsQueue.add({lat: 1, lng: 2, recorded_at: new Date().toISOString()})")
    page.reload()
    assert page.evaluate('(async () => (await gpsQueue.list()).length)()') == 1
    page.evaluate("window.fetch = async () => { throw new Error('offline'); }; tracking = true; flushQueue()")
    assert page.evaluate('(async () => (await gpsQueue.list()).length)()') == 1
    page.evaluate("window.fetch = async () => ({ok: true, json: async () => ({accepted: true})}); flushQueue()")
    assert page.evaluate('(async () => (await gpsQueue.list()).length)()') == 0
    assert page.evaluate('pointsSent') == 1


def test_queue_is_scoped_per_streamer(browser_page, web_origin):
    page = browser_page
    page.goto(web_origin + '/pwa/')
    page.add_script_tag(url=web_origin + '/pwa/queue.js')
    assert page.evaluate('''async () => {
      const a = new GPSQueue('streamer-a');
      const b = new GPSQueue('streamer-b');
      await a.add({lat: 1, lng: 2});
      await b.add({lat: 3, lng: 4});
      await a.clear();
      return (await a.list()).length === 0 && (await b.list()).length === 1;
    }''')
