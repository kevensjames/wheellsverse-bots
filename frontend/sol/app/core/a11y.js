// SOL member app — core/a11y.js
// Classic script (shared global scope); loaded in order by app.html.
// Route changes for screen readers and keyboard users: nav() (core/router.js) calls
// solRouteChanged(page), which names the page in the document title and moves focus to
// the page's h1 (tabindex -1). The skip link moves focus to the active page's h1.

function _pageHeading(page) {
  const el = document.getElementById('page-' + page);
  const h = el ? el.querySelector('h1') : null;
  if (h && !h.hasAttribute('tabindex')) h.setAttribute('tabindex', '-1');
  return h;
}

function solRouteChanged(page) {
  const h = _pageHeading(page);
  if (!h) return;
  const label = (h.textContent || '').replace(/\s+/g, ' ').trim();
  if (label) document.title = 'Sol — ' + label;
  try { h.focus(); } catch (e) {}
}

// "Skip to content": focus the active page's heading, inside main. Returns false so the
// link does not also change the address (#main).
function skipToContent(e) {
  const page = document.querySelector('.page.active');
  const target = (page && page.querySelector('h1')) || document.getElementById('main');
  if (!target) return true;
  if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
  if (e) e.preventDefault();
  try { target.focus(); } catch (err) {}
  return false;
}
