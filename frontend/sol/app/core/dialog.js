// SOL member app — core/dialog.js
// Classic script (shared global scope). SolDialog: the ONE dialog/sheet focus
// manager. Centralizes the accessible-dialog mechanics that were duplicated
// across ~7 bespoke open/close/_trapKey trios (bank remove, premium cancel,
// goal create/edit/progress/confirm, discover circle-detail, community report,
// mobile More sheet). Pure DOM mechanics — no server data, no page state.
//
// Contract (preserved from the audited dialogs):
//   • visible-only focus boundaries (offsetParent !== null; disabled excluded)
//   • radio groups collapse to ONE tab stop (checked, else first) — no-op if none
//   • Tab / Shift+Tab loop first<->last; escaped focus is pulled back in
//   • Escape closes ONLY when canClose() allows (busy-guarded)
//   • focus enters the dialog on open; restores to a connected+visible opener on close
//   • exactly one keydown listener at a time (no duplicates on repeated open)
window.SolDialog = (function () {
  let active = null;   // { el, opts, opener }

  const resolve = (d) => (typeof d === 'string' ? document.getElementById(d) : d) || null;
  // The open-class is stamped onto the element on open (data-sol-open) so close()
  // uses the right class even when the dialog isn't the currently-active one.
  const openClassOf = (o) => (o && o.openClass) || 'is-open';
  const elOpenClass = (d) => d.dataset.solOpen || 'is-open';

  // Visible, enabled focusables — radio groups collapsed to a single stop.
  function focusables(d) {
    const els = [...d.querySelectorAll('input,select,button,textarea,a[href]')]
      .filter((x) => !x.disabled && x.offsetParent !== null);
    const seen = new Set();
    const out = [];
    for (const x of els) {
      if (x.type === 'radio' && x.name) {
        if (seen.has(x.name)) continue;
        seen.add(x.name);
        const group = els.filter((y) => y.type === 'radio' && y.name === x.name);
        out.push(group.find((y) => y.checked) || group[0]);
      } else out.push(x);
    }
    return out;
  }

  function canClose(rec) {
    const c = rec.opts.canClose;
    if (typeof c === 'function') { try { return !!c(rec.el); } catch (e) { return true; } }
    return rec.el.dataset.busy !== '1';   // default busy-guard
  }

  function onKey(e) {
    if (!active) return;
    const d = active.el;
    if (!d.classList.contains(elOpenClass(d))) return;   // only trap while open
    if (e.key === 'Escape') {
      e.preventDefault();
      if (active.opts.closeOnEscape === false) return;
      if (!canClose(active)) return;
      SolDialog.close(d);
      return;
    }
    if (e.key !== 'Tab') return;
    const f = focusables(d);
    if (!f.length) { e.preventDefault(); return; }
    const first = f[0], last = f[f.length - 1];
    const a = document.activeElement;
    if (!d.contains(a)) { e.preventDefault(); first.focus(); return; }   // pull escaped focus back
    let cur = a;
    if (a.type === 'radio' && a.name) cur = f.find((x) => x.type === 'radio' && x.name === a.name) || a;
    if (e.shiftKey && cur === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && cur === last) { e.preventDefault(); first.focus(); }
  }

  function landFocus(rec) {
    const d = rec.el, o = rec.opts;
    const pick = () => {
      if (!d.classList.contains(elOpenClass(d))) return;   // closed again before focus landed
      let t = null;
      if (typeof o.getInitialFocus === 'function') { try { t = o.getInitialFocus(d); } catch (e) {} }
      else if (o.initialFocus) t = typeof o.initialFocus === 'string' ? d.querySelector(o.initialFocus) : o.initialFocus;
      if (!t) t = focusables(d)[0];
      if (t && typeof t.focus === 'function') { try { t.focus(); } catch (e) {} }
    };
    // A sliding sheet (mobileSheet) is mid-transition at 0ms, so focus after two frames.
    if (o.mobileSheet) requestAnimationFrame(() => requestAnimationFrame(pick));
    else setTimeout(pick, 0);
  }

  return {
    open(dlg, opts = {}) {
      const d = resolve(dlg);
      if (!d) return;
      const rec = { el: d, opts, opener: opts.opener || document.activeElement || null };
      active = rec;
      d.dataset.busy = '0';
      d.dataset.solOpen = openClassOf(opts);   // remember the open-class for close()
      d.classList.add(openClassOf(opts));
      if (opts.ariaHidden) d.setAttribute('aria-hidden', 'false');
      document.removeEventListener('keydown', onKey, true);   // never stack listeners
      document.addEventListener('keydown', onKey, true);
      if (typeof opts.onOpen === 'function') { try { opts.onOpen(d); } catch (e) {} }
      if (opts.initialFocus !== false) landFocus(rec);
    },

    // close(dlg, { restoreFocus }) — restoreFocus:false lets the caller land focus
    // itself (used after a re-render destroys the opener). Domain busy-guards live
    // in the caller's close wrapper (e.g. bank remove blocks close mid-delete).
    close(dlg, opts = {}) {
      const d = resolve(dlg) || (active && active.el);
      if (!d) return;
      const rec = active && active.el === d ? active : { el: d, opts: {}, opener: null };
      const o = rec.opts;
      const oc = elOpenClass(d);
      const wasOpen = d.classList.contains(oc);
      d.classList.remove(oc);
      if (o.ariaHidden || d.hasAttribute('aria-hidden')) d.setAttribute('aria-hidden', 'true');
      document.removeEventListener('keydown', onKey, true);
      if (typeof o.onClose === 'function') { try { o.onClose(d); } catch (e) {} }
      const restore = opts.restoreFocus !== false && o.restoreFocus !== false;
      const opener = rec.opener;
      if (active && active.el === d) active = null;
      if (wasOpen && restore && opener && opener.isConnected && opener.offsetParent !== null
          && typeof opener.focus === 'function') {
        try { opener.focus(); } catch (e) {}
      }
    },

    isOpen(dlg) {
      const d = resolve(dlg);
      return !!(d && d.classList.contains(elOpenClass(d)));
    },

    // Content changed after open (dynamic dialog): focusables are recomputed on
    // every Tab, so nothing to rebuild — provided for API completeness.
    refresh() {},

    // Detach the trap for a dialog (e.g. it was removed from the DOM).
    destroy(dlg) {
      const d = resolve(dlg);
      if (active && (!d || active.el === d)) { document.removeEventListener('keydown', onKey, true); active = null; }
    },
  };
})();
