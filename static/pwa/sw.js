/**
 * RatoNet GPS Tracker — Service Worker
 * Cache shell. The client persists GPS points in IndexedDB.
 */

const CACHE_NAME = 'ratonet-pwa-v2';
const SHELL_URLS = [
  '/pwa/',
  '/pwa/tracker.html',
  '/pwa/queue.js',
  '/static/pwa/manifest.json',
];

// --- Install: cacheia shell ---
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

// --- Activate: limpa caches antigos ---
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k.startsWith('ratonet-pwa-') && k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// --- Fetch: network-first com fallback para cache ---
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // API calls: network only (não cacheia dados dinâmicos)
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin ||
      !(url.pathname.startsWith('/pwa/') || url.pathname.startsWith('/static/pwa/'))) {
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        // Cacheia resposta válida
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
