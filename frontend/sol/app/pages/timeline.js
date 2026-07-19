// SOL member app — pages/timeline.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Timeline ────────────────────────────────────────────────────────────────────
async function loadTimeline() {
  const el = document.getElementById('timelineContent');
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const t = await api('/timeline/me');
    const nc=t.next_contribution, up=t.upcoming_payout;
    const upAmt = up ? (up.amount_cents ?? up.net_cents) : null;
    const upDate = up ? (up.date ?? up.payout_date ?? up.estimated_date) : null;
    const out = [`<div class="cards">
      <div class="card"><div class="card-label">Next contribution</div><div class="card-val">${nc?fmt$(nc.amount_cents):'—'}</div>${nc?`<div style="font-size:.8rem;color:var(--muted)">${esc(nc.group_name)} · due ${fmtDate(nc.due_date)}</div>`:''}</div>
      <div class="card"><div class="card-label">Payments remaining</div><div class="card-val">${t.remaining_payments??'—'}</div></div>
      <div class="card"><div class="card-label">Upcoming payout</div><div class="card-val" style="color:var(--gold)">${upAmt!=null?fmt$(upAmt):'—'}</div>${upDate?`<div style="font-size:.8rem;color:var(--muted)">${fmtDate(upDate)}</div>`:''}</div>
    </div>`];
    const cp=t.circle_progress||[];
    if (cp.length) {
      out.push(`<h2 style="font-size:1.1rem;margin:1.5rem 0 1rem;font-family:var(--font-display)">Circle progress</h2>`);
      out.push(cp.map(c=>{ const pct=c.total_cycles?Math.round(c.current_cycle/c.total_cycles*100):0; return `<div class="card" style="margin-bottom:.75rem">
        <div style="display:flex;justify-content:space-between;margin-bottom:.4rem"><strong>${esc(c.group_name)}</strong><span style="font-size:.85rem;color:var(--muted)">Cycle ${c.current_cycle} of ${c.total_cycles}</span></div>
        <div style="background:rgba(0,0,0,.08);border-radius:99px;height:8px;overflow:hidden"><div style="background:var(--green);height:100%;width:${pct}%"></div></div>
        ${c.has_received_payout?'<div style="font-size:.8rem;color:var(--green);margin-top:.3rem">✓ Payout received</div>':''}</div>`; }).join(''));
    }
    const ph=t.payment_history||[];
    if (ph.length) {
      out.push(`<h2 style="font-size:1.1rem;margin:1.5rem 0 1rem;font-family:var(--font-display)">Recent payments</h2>`);
      out.push(`<div class="table-wrap"><table><thead><tr><th>Date</th><th>Amount</th><th>Status</th></tr></thead><tbody>${ph.map(p=>`<tr><td style="color:var(--muted)">${esc(fmtDate(p.created_at))}</td><td>${fmt$(p.amount_cents)}</td><td>${statusChip(p.status)}</td></tr>`).join('')}</tbody></table></div>`);
    }
    el.innerHTML = out.join('');
  } catch (e) { el.innerHTML = `<div class="empty"><p>Couldn't load your timeline.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadTimeline()">Retry</button></div>`; }
}
