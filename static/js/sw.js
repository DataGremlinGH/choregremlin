// Chore Gremlin Service Worker
const CACHE_NAME = 'choregremlin-v6';
const STATIC_ASSETS = [
  '/',
  '/static/css/bootstrap.min.css',
  '/static/css/family-hub.css',
  '/static/css/tokens.css',
  '/static/js/bootstrap.bundle.min.js',
  '/static/js/family-hub.js',
  '/static/js/live-alerts.js',
  '/static/js/kid-ticker.js',
  '/static/js/drop-chores.js',
  '/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  // Never cache live APIs; they must always reach the server.
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;

  // Network-first for navigation, cache-first for static assets
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/'))
    );
  } else {
    event.respondWith(
      caches.match(event.request).then((cached) =>
        cached || fetch(event.request).then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        }).catch(() => cached)
      )
    );
  }
});


// Phase 14: Web Push and notification click handling
self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (e) {
    payload = { title: 'Chore Gremlin', body: event.data ? event.data.text() : '' };
  }
  const title = payload.title || 'Chore Gremlin';
  const options = {
    body: payload.body || 'A new family alert is ready.',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    tag: payload.tag || 'choregremlin-alert',
    data: { url: payload.url || '/' },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});

self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type !== 'broadcast' || !data.title) return;
  self.registration.showNotification(data.title, {
    body: data.body || '',
    icon: '/static/icons/icon-192.png',
    data: { url: data.url || '/' },
  });
});
