// Self-contained "new build available" watcher — works on any page, no server
// endpoint needed.
//
// It snapshots the ?v=ts-<mtime> cache-buster stamps of the assets THIS page
// loaded (script src + link href), then periodically re-fetches the page's own
// HTML (cache-busted) and re-reads those stamps. If any asset's stamp has
// INCREASED, a newer build shipped → show a one-click reload banner.
//
// Because it compares the page to a fresh copy of ITSELF, there are no false
// positives and no cross-page asset confusion (chat.html watches style.css +
// chat.js; admin.html watches its own assets; etc.). The stamps come from
// scripts/stamp_static_assets.py, which ties ?v=ts-<n> to each file's mtime.
(function () {
  "use strict";

  // Register the network-first service worker so the INSTALLED (home-screen)
  // PWA always fetches the latest build instead of serving iOS's sticky stale
  // snapshot. Failure is non-fatal — the page works fine without it.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker
        .register("/kai-ui/sw.js", { scope: "/kai-ui/" })
        .catch(function () {});
    });
  }

  function collectStamps(doc) {
    var out = {};
    doc.querySelectorAll("script[src], link[href]").forEach(function (el) {
      var url = el.getAttribute("src") || el.getAttribute("href") || "";
      var m = url.match(/([^"'?\s]+)\?v=ts-(\d+)/);
      if (m) out[m[1]] = parseInt(m[2], 10);
    });
    return out;
  }

  var loaded = collectStamps(document);
  if (!Object.keys(loaded).length) return; // nothing stamped → nothing to watch
  var shown = false;

  function showBanner() {
    if (shown || document.getElementById("kai-reload-banner")) return;
    shown = true;
    var host = document.body || document.documentElement;
    var bar = document.createElement("div");
    bar.id = "kai-reload-banner";
    bar.style.cssText =
      "position:fixed;top:0;left:0;right:0;z-index:99999;background:#1d4ed8;" +
      "color:#fff;font:600 14px/1.4 system-ui,sans-serif;padding:10px 14px;" +
      "display:flex;align-items:center;gap:10px;box-shadow:0 2px 8px rgba(0,0,0,.3)";
    var msg = document.createElement("span");
    msg.textContent = "🔄 A newer version is available.";
    msg.style.flex = "1";
    var reload = document.createElement("button");
    reload.textContent = "Reload now";
    reload.style.cssText =
      "background:#fff;color:#1d4ed8;border:0;border-radius:6px;padding:6px 14px;" +
      "font-weight:700;cursor:pointer";
    reload.addEventListener("click", function () { location.reload(); });
    var dismiss = document.createElement("button");
    dismiss.textContent = "✕";
    dismiss.setAttribute("aria-label", "Dismiss");
    dismiss.style.cssText =
      "background:transparent;color:#fff;border:0;font-size:16px;cursor:pointer";
    dismiss.addEventListener("click", function () { bar.remove(); });
    bar.appendChild(msg);
    bar.appendChild(reload);
    bar.appendChild(dismiss);
    host.insertBefore(bar, host.firstChild);
  }

  function check() {
    if (shown) return;
    fetch(location.pathname + "?_wv=" + new Date().getTime(), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        if (!html) return;
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = collectStamps(doc);
        for (var k in fresh) {
          if (loaded[k] != null && fresh[k] > loaded[k]) { showBanner(); return; }
        }
      })
      .catch(function () { /* offline / transient — retry next tick */ });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") check();
  });
  setInterval(check, 90000);
  setTimeout(check, 4000); // first check shortly after load
})();
