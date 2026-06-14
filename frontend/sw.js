// WheellsVerse Admin Service Worker
//
// Strategy:
//   /admin, /admin/*       → network-only  (always get the freshest dashboard
//                                           — the in-app version watcher
//                                           handles update prompts)
//   /api/*                 → network-only  (never cache live API data)
//   /manifest.json,
//   /favicon.svg, /favicon.ico,
//   other static assets    → cache-first with network fallback + opportunistic
//                                           refresh in background
//
// Bump CACHE_VERSION on any SW change so old caches get evicted on next visit.

const CACHE_VERSION = 'wv-admin-v1';
const PRECACHE = [
  '/manifest.json',
  '/favicon.svg',
  '/favicon.ico',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Always-fresh paths — never cache
  if (url.pathname === '/admin' ||
      url.pathname.startsWith('/admin/') ||
      url.pathname.startsWith('/api/')) {
    return; // let the browser do its default network fetch
  }

  // Cache-first for static assets
  event.respondWith(
    caches.match(req).then((cached) => {
      const networked = fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put(req, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => cached); // offline → cached if present
      return cached || networked;
    })
  );
});
