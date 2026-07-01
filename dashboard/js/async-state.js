/* async-state.js — reusable fetch→render state wrapper for the Command Center.
 *
 * Wraps a fetch→render cycle in consistent loading / empty / error / retry
 * states, so views stop failing silently (see the 42 empty catch{} blocks the
 * frontend audit found) and async changes are announced to assistive tech.
 *
 * No framework, no build step. Include with:
 *   <script src="js/async-state.js"></script>
 * then adopt per view, one at a time:
 *   refreshOutputs.run = asyncView({
 *     target: "#out-content",
 *     fetcher: () => api("/api/outputs"),
 *     emptyText: "No outputs yet",
 *     onError: (e) => toast("Outputs failed: " + e.message, "error"),
 *     render: (data, mount) => { ...build DOM into mount... },
 *   });
 *
 * XSS-safe by construction (textContent / createElement, never innerHTML).
 */
(function (global) {
  "use strict";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text; // textContent = XSS-safe
    return n;
  }

  function stateBox(kind, msg, onRetry) {
    var box = el("div", "asv asv-" + kind);
    box.setAttribute("role", kind === "error" ? "alert" : "status");
    box.setAttribute("aria-live", "polite");
    box.appendChild(el("div", "asv-msg", msg));
    if (kind === "error" && typeof onRetry === "function") {
      var btn = el("button", "asv-retry", "Retry");
      btn.type = "button";
      btn.addEventListener("click", onRetry);
      box.appendChild(btn);
    }
    return box;
  }

  /**
   * @param {object}          o
   * @param {string|Element}  o.target       selector or node to render into
   * @param {Function}        o.fetcher      async () => data (e.g. () => api('/api/x'))
   * @param {Function}        o.render       (data, mount) => void
   * @param {Function}        [o.isEmpty]    (data) => boolean (default: empty array/obj/null)
   * @param {string}          [o.loadingText]
   * @param {string}          [o.emptyText]
   * @param {Function}        [o.onError]    (err) => void (e.g. toast / re-auth)
   * @returns {Function}      run() — call to (re)load; returned so callers can refresh.
   */
  function asyncView(o) {
    var mount = typeof o.target === "string"
      ? document.querySelector(o.target) : o.target;
    if (!mount) return function () {};

    var isEmpty = o.isEmpty || function (d) {
      if (d == null) return true;
      if (Array.isArray(d)) return d.length === 0;
      if (typeof d === "object") return Object.keys(d).length === 0;
      return false;
    };

    async function run() {
      mount.replaceChildren(stateBox("loading", o.loadingText || "Loading…"));
      try {
        var data = await o.fetcher();
        if (isEmpty(data)) {
          mount.replaceChildren(stateBox("empty", o.emptyText || "Nothing here yet"));
          return;
        }
        mount.replaceChildren();
        o.render(data, mount);
      } catch (err) {
        if (o.onError) { try { o.onError(err); } catch (_) {} }
        var msg = (err && err.message) ? err.message : "Request failed";
        mount.replaceChildren(stateBox("error", "Couldn’t load: " + msg, run));
      }
    }
    run();
    return run;
  }

  global.asyncView = asyncView;
})(window);
