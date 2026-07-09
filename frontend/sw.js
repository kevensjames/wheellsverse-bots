// WheellsVerse Service Worker — SELF-DESTRUCT / KILL SWITCH.
//
// The previous version cached pages cache-first (including /sol/*), which served
// users STALE HTML after every deploy — new content only appeared on a second
// visit. No page registers a service worker anymore, so any SW still active in a
// browser is a leftover from that past deploy.
//
// This replacement does nothing but clean up: on activate it deletes every
// cache, unregisters itself, and reloads open tabs — so affected browsers get
// fresh content and stop caching pages. Browsers pick this up automatically on
// their next SW update check (navigation / ~24h). New visitors never register a
// SW at all, so for them this file is simply never installed.

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // Drop every cached response — the stale HTML lived here.
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => caches.delete(k)));
    // Remove this service worker entirely.
    await self.registration.unregister();
    // Reload any open tabs so they show the fresh, network-served content.
    const clients = await self.clients.matchAll({ type: 'window' });
    for (const client of clients) {
      client.navigate(client.url);
    }
  })());
});

// No fetch handler → every request goes straight to the network (always fresh).
