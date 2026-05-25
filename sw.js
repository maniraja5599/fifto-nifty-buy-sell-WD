const CACHE_NAME = 'fifto-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/fifto_logo.png',
  '/manifest.json'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    })
  );
});

self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request).then((cachedResponse) => {
      return cachedResponse || fetch(e.request).catch(() => {
        // Fallback for API calls if offline
        if (e.request.url.includes('/api/')) {
          return new Response(JSON.stringify({ error: "Offline" }), {
            headers: { 'Content-Type': 'application/json' }
          });
        }
      });
    })
  );
});
