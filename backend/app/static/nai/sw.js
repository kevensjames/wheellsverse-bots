// KAI service worker — keeps the installed (home-screen) PWA fresh.
//
// WHY: iOS standalone web apps keep their own sticky cache and can serve a
// stale start page for a long time, surviving reloads. A NETWORK-FIRST service
// worker fixes that: when online you always get the latest build; the cache is
// only a fallback for when the network is unavailable.
//
// SAFETY: only same-origin GET navigations + static assets are intercepted.
// POST/PUT, cross-origin, API calls, and streaming (SSE) are NOT touched, so
// chat sending and streaming behave exactly as before. We only cache clean
// 200 "basic" responses. skipWaiting + clients.claim make a new build take
// over promptly; and because it's network-first, even an old SW still serves
// fresh content — so this can't "stick" a stale page.
const CACHE = "kai-cache-v1";
const ASSET_RE = /\.(?:html|css|js|mjs|png|jpg|jpeg|gif|svg|webp|ico|woff2?|ttf|json|webmanifest)$/i;

self.addEventListener("install", function () {
  self.skipWaiting(); // activate immediately; don't wait for old tabs to close
});

self.addEventListener("activate", function (event) {
  event.waitUntil((async function () {
    var keys = await caches.keys();
    await Promise.all(keys.filter(function (k) { return k !== CACHE; })
                          .map(function (k) { return caches.delete(k); }));
    await self.clients.claim(); // control already-open in-scope pages now
  })());
});

self.addEventListener("fetch", function (event) {
  var req = event.request;
  if (req.method !== "GET") return; // never intercept POST/PUT/etc.
  var url;
  try { url = new URL(req.url); } catch (e) { return; }
  if (url.origin !== self.location.origin) return; // leave cross-origin alone
  var isNavigation = req.mode === "navigate";
  var isAsset = ASSET_RE.test(url.pathname);
  if (!isNavigation && !isAsset) return; // APIs / SSE / other GETs: pass through
  event.respondWith(networkFirst(req));
});

async function networkFirst(req) {
  try {
    var fresh = await fetch(req);
    if (fresh && fresh.ok && fresh.type === "basic") {
      var cache = await caches.open(CACHE);
      cache.put(req, fresh.clone()); // refresh the offline fallback copy
    }
    return fresh;
  } catch (err) {
    var cached = await caches.match(req);
    if (cached) return cached; // offline → last-known copy
    throw err; // genuinely offline + uncached → fail normally
  }
}
