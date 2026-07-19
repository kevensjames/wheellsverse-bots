// SOL member app — pages/trust.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Trust / SOL Score ───────────────────────────────────────────────────────────
async function loadTrust() {
  const el = document.getElementById('trustContent');
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const t = await api('/trust/me');
    const pct = t.max_score ? Math.round(t.sol_score/t.max_score*100) : 0;
    const comps = t.components||{};
    const compRows = Object.entries(comps).map(([k,v])=>`<div style="display:flex;justify-content:space-between;font-size:.85rem;padding:.3rem 0"><span style="text-transform:capitalize">${esc(k.replace(/_/g,' '))}</span><strong>${Math.round(v)}</strong></div>`).join('');
    const badges = t.badges||[];
    const badgeGrid = badges.length ? `<div class="cards">${badges.map(b=>`<div class="card" style="text-align:center"><div style="font-size:1.5rem">🏅</div><div style="font-weight:700;font-size:.9rem">${esc(b.title)}</div><div style="font-size:.75rem;color:var(--muted)">${esc(b.description||'')}</div></div>`).join('')}</div>` : '<div class="empty">No badges yet — pay on time and complete circles to earn them.</div>';
    el.innerHTML = `
      <div class="card" style="text-align:center;margin-bottom:1.5rem;border-color:rgba(232,147,36,.3)">
        <div style="font-size:3rem;font-weight:800;color:var(--gold);font-family:var(--font-display)">${t.sol_score}</div>
        <div style="font-size:.85rem;color:var(--muted)">of ${t.max_score} · SOL Score</div>
        <div style="background:rgba(0,0,0,.08);border-radius:99px;height:10px;overflow:hidden;margin-top:.75rem"><div style="background:linear-gradient(90deg,var(--gold),var(--green));height:100%;width:${pct}%"></div></div>
      </div>
      <h2 style="font-size:1.1rem;margin-bottom:.5rem;font-family:var(--font-display)">How it's built</h2>
      <div class="card" style="margin-bottom:1.5rem">${compRows}</div>
      <h2 style="font-size:1.1rem;margin-bottom:1rem;font-family:var(--font-display)">Badges</h2>${badgeGrid}`;
  } catch (e) { el.innerHTML = `<div class="empty"><p>Couldn't load your SOL Score.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadTrust()">Retry</button></div>`; }
}
