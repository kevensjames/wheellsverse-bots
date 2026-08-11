// ============================================================================
// Cinematic spatial transitions (Increment 19).
// One environment transforming around KAI, not 20 pages. Opening a tab pulls a
// workspace overlay up over the field; KAI stays central. Honors reduced-motion
// (durations collapse via tokens.css, so this just toggles classes).
// ============================================================================
import { bus } from './state.js';

export function mountWorkspace(root) {
  const ws = document.createElement('div');
  ws.className = 'workspace';
  ws.innerHTML = `<div class="frame"><div class="ws-head"><h2></h2>
      <button class="iconbtn close ws-head-close" aria-label="Close">✕</button></div>
      <div class="ws-body"></div></div>`;
  root.appendChild(ws);
  const body = ws.querySelector('.ws-body'), title = ws.querySelector('h2');
  let current = null;

  function close() {
    ws.classList.remove('open');
    document.querySelectorAll('.tab.active').forEach(t => t.classList.remove('active'));
    current = null;
    bus.emit('workspace:close');
  }
  ws.querySelector('.ws-head-close').onclick = close;
  ws.addEventListener('click', e => { if (e.target === ws) close(); });
  addEventListener('keydown', e => { if (e.key === 'Escape' && ws.classList.contains('open')) close(); });

  // open(name, titleText, renderFn) — renderFn(container) fills the frame body
  function open(name, titleText, render) {
    if (current === name) return close();
    current = name;
    title.textContent = titleText;
    body.replaceChildren();
    render(body);
    ws.classList.add('open');
    bus.emit('sound:cue', 'send');
    bus.emit('workspace:open', name);
  }

  return { open, close, get current() { return current; } };
}
