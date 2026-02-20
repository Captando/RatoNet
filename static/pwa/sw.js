/**
 * RatoNet GPS Tracker — Service Worker
 * Cache shell + enfileira GPS points quando offline.
 */

const CACHE_NAME = 'ratonet-pwa-v1';
const SHELL_URLS = [
  '/pwa/',
  '/pwa/tracker.html',
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
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// --- Fetch: network-first com fallback para cache ---
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // API calls: network only (não cacheia dados dinâmicos)
  if (request.url.includes('/api/')) {
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

// --- Background Sync: envia GPS enfileirado ---
self.addEventListener('sync', (event) => {
  if (event.tag === 'gps-queue') {
    event.waitUntil(flushGPSQueue());
  }
});

async function flushGPSQueue() {
  // Lê fila do IndexedDB via mensagem para o client
  const clients = await self.clients.matchAll();
  for (const client of clients) {
    client.postMessage({ type: 'flush-gps-queue' });
  }
}
