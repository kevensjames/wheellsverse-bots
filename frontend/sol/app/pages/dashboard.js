// SOL member app — pages/dashboard.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ═══ Dashboard — member command center ═══════════════════════════════════════
// One consolidated, partial-failure-safe load (Promise.allSettled) feeds every
// section, so one endpoint failing degrades only its own card, never the page.
const DASH_ACTIVE = ['ACTIVE', 'COLLECTING', 'SETTLING'];

async function loadDashboard() {
  renderDashSkeletons();
  const R = await Promise.allSettled([
    api('/subscriptions/me'), api('/groups'), api('/trust/me'),
    api('/timeline/me'), api('/bank/list'), api('/notifications'), api('/goals'),
  ]);
  const ok = i => R[i].status === 'fulfilled';
  const v = i => ok(i) ? R[i].value : null;
  const groups = (v(1) || []).filter(g => !isTestCircle(g));  // never show internal test circles
  // /notifications returns { notifications:[...], unread_count } — extract the array.
  const D = { sub: v(0), groups, trust: v(2), tl: v(3), banks: v(4) || [], notes: (v(5) && v(5).notifications) || [], goals: v(6) || [], me,
    ok: { sub: ok(0), groups: ok(1), trust: ok(2), tl: ok(3), banks: ok(4), notes: ok(5), goals: ok(6) } };
  renderDashHero(D); renderDashAttention(D); renderDashSummary(D);
  renderDashCircles(D); renderDashTimeline(D);
  renderDashScore(D); renderDashPremium(D); renderDashGoals(D); renderDashTrust(D);
}

function dashGreeting() { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'; }
function dashFirstName() { const n = (me && (me.full_name || me.email)) || ''; return esc(n.split('@')[0].split(' ')[0] || 'there'); }
function dashActive(D) { return D.groups.filter(g => DASH_ACTIVE.includes(g.status)); }
function dashForming(D) { return D.groups.filter(g => g.status === 'FORMING'); }
function _dashDate(d) { return fmtDate(d, { month: 'short', day: 'numeric' }) || null; }   // compact "Jul 19" (year implied in context)
function dashIdVerified() { const k = ((me && me.kyc_status) || '').toUpperCase(); return k === 'APPROVED' || k === 'VERIFIED'; }

// Next contribution — prefer the timeline's authoritative value; else derive from
// the soonest active-circle payout day (flagged as an estimate).
function dashNextContribution(D) {
  const nc = D.tl && D.tl.next_contribution;
  if (nc && nc.amount_cents != null) return { amount: nc.amount_cents, label: nc.group_name, date: nc.due_date };
  const act = dashActive(D).filter(g => g.payout_day_of_month != null);
  if (!act.length) return null;
  const s = act.map(g => ({ g, d: _nextDayOfMonth(new Date(), g.payout_day_of_month) })).sort((a, b) => a.d - b.d)[0];
  return { amount: s.g.contribution_cents, label: s.g.name, date: s.d.toISOString(), estimate: true };
}
function dashNextPayout(D) {
  const up = D.tl && D.tl.upcoming_payout;
  if (!up) return null;
  const amount = up.amount_cents != null ? up.amount_cents : up.net_cents;
  const date = up.date || up.payout_date || up.estimated_date;
  if (amount == null && !date) return null;
  return { amount, date, estimate: !up.date && !up.payout_date };
}
function dashMonthly(D) { return dashActive(D).reduce((s, g) => s + (g.contribution_cents || 0), 0); }
function dashOrbProgress(D) {
  const cp = (D.trust && D.trust.circle_progress) || (D.tl && D.tl.circle_progress) || [];
  if (cp.length) return Math.max(0, Math.min(1, cp.reduce((s, c) => s + (c.total_cycles ? c.current_cycle / c.total_cycles : 0), 0) / cp.length));
  const act = dashActive(D); if (!act.length) return 0;
  return Math.max(0, Math.min(1, act.reduce((s, g) => s + (g.member_count || 0) / (g.max_members || 1), 0) / act.length));
}

// Context-sensitive hero primary action (priority: verify > bank > join > view).
function dashHeroAction(D) {
  if (!dashIdVerified())
    return { message: 'Verify your identity to start saving with circles.', primary: { label: 'Complete verification', action: "nav('kyc')" }, secondary: { label: 'Discover circles', action: "nav('discover')" } };
  if (!(D.banks || []).length)
    return { message: 'Link a bank account to make and receive circle payments.', primary: { label: 'Connect bank', action: "nav('bank')" }, secondary: { label: 'Discover circles', action: "nav('discover')" } };
  const active = dashActive(D);
  if (!active.length)
    return { message: "You're all set — join a savings circle to get started.", primary: { label: 'Discover circles', action: "nav('discover')" }, secondary: { label: 'Create circle', action: "nav('groups')" } };
  return { message: `You're active in ${active.length} circle${active.length === 1 ? '' : 's'}. Keep contributions on time to grow your SOL Score.`, primary: { label: 'View circles', action: "nav('groups')" }, secondary: { label: 'View timeline', action: "nav('timeline')" } };
}

function renderDashHero(D) {
  const el = document.getElementById('dashHero'); if (!el) return;
  const premium = !!(D.sub && D.sub.is_premium);
  const nc = dashNextContribution(D), np = dashNextPayout(D), act = dashHeroAction(D);
  el.innerHTML = `
    <div class="hero-copy">
      <div class="hero-greeting">${dashGreeting()}, ${dashFirstName()}</div>
      <p class="hero-sub">${esc(act.message)}</p>
      <div class="hero-stats">
        <div><span class="hs-label">Next contribution</span><span class="hs-val tnum">${nc && nc.amount != null ? fmt$(nc.amount) : '—'}</span>${nc && _dashDate(nc.date) ? `<span class="hs-meta">${nc.estimate ? 'est. ' : ''}${_dashDate(nc.date)}</span>` : ''}</div>
        <div><span class="hs-label">Next payout</span><span class="hs-val tnum">${np && np.amount != null ? fmt$(np.amount) : '—'}</span>${np && _dashDate(np.date) ? `<span class="hs-meta">${np.estimate ? 'est. ' : ''}${_dashDate(np.date)}</span>` : ''}</div>
        <div><span class="hs-label">Active circles</span><span class="hs-val tnum">${dashActive(D).length}</span></div>
      </div>
      <div class="hero-actions">
        <button type="button" class="btn btn-primary" onclick="${act.primary.action}">${act.primary.label}</button>
        <button type="button" class="btn btn-ghost" onclick="${act.secondary.action}">${act.secondary.label}</button>
      </div>
    </div>
    <div class="hero-orb">
      <span class="premium-pill${premium ? ' is-premium' : ''}">${premium ? 'Premium' : 'Free plan'}</span>
      <canvas id="solOrb" width="220" height="220" aria-hidden="true"></canvas>
    </div>`;
  SolOrb.render({ premium, progress: dashOrbProgress(D) });
}

function renderDashAttention(D) {
  const el = document.getElementById('dashAttention'); if (!el) return;
  const items = [];
  if (!dashIdVerified()) items.push({ pr: 1, cls: 'warning', title: 'Verify your identity', reason: 'Required before you can join a circle.', label: 'Verify ID', action: "nav('kyc')" });
  if (D.ok.banks && !(D.banks || []).length) items.push({ pr: 2, cls: 'warning', title: 'Connect a bank account', reason: 'Needed to make and receive circle payments.', label: 'Connect bank', action: "nav('bank')" });
  if ((me && me.failed_payments) > 0) items.push({ pr: 0, cls: 'failed', title: 'A payment needs attention', reason: `${esc(me.failed_payments)} failed payment${me.failed_payments === 1 ? '' : 's'} on record.`, label: 'Review payments', action: "nav('payments')" });
  const nc = D.tl && D.tl.next_contribution;
  if (nc && nc.due_date) { const days = Math.ceil((new Date(nc.due_date) - new Date()) / 86400000); if (days <= 5) items.push({ pr: 0, cls: 'pending', title: 'Contribution coming up', reason: `${nc.amount_cents != null ? fmt$(nc.amount_cents) + ' ' : ''}for ${esc(nc.group_name || 'your circle')} due ${fmtDate(nc.due_date)}.`, label: 'View circles', action: "nav('groups')" }); }
  const unread = (D.notes || []).filter(n => !n.read_at).length;
  if (D.ok.notes && unread) items.push({ pr: 3, cls: 'active', title: `${unread} unread alert${unread === 1 ? '' : 's'}`, reason: 'Updates about your circles and payments.', label: 'View alerts', action: "nav('notifications')" });
  items.sort((a, b) => a.pr - b.pr);
  if (!items.length) { el.innerHTML = `<div class="attn-card is-clear"><div class="attn-card__check" aria-hidden="true">✓</div><div class="attn-card__body"><div class="attn-card__title">You're all caught up</div><div class="attn-card__reason">No actions need your attention right now.</div></div></div>`; return; }
  const t = items[0];
  el.innerHTML = `<div class="attn-card status--${t.cls}"><div class="attn-card__body"><div class="attn-card__eyebrow">Needs your attention</div><div class="attn-card__title">${t.title}</div><div class="attn-card__reason">${t.reason}</div></div><button type="button" class="btn btn-primary btn--sm" onclick="${t.action}">${t.label}</button>${items.length > 1 ? `<div class="attn-card__more">+${items.length - 1} more</div>` : ''}</div>`;
}

function renderDashSummary(D) {
  const el = document.getElementById('dashSummary'); if (!el) return;
  const nc = dashNextContribution(D), np = dashNextPayout(D), active = dashActive(D).length, forming = dashForming(D).length;
  const card = (label, val, meta) => `<div class="sum-card"><div class="sum-label">${label}</div><div class="sum-val tnum">${val}</div>${meta ? `<div class="sum-hint">${meta}</div>` : ''}</div>`;
  el.innerHTML =
    card('Contributions / cycle', active ? fmt$(dashMonthly(D)) : '—', active ? 'across active circles' : 'no active circles') +
    card('Next contribution', nc && nc.amount != null ? fmt$(nc.amount) : '—', nc && _dashDate(nc.date) ? `${nc.estimate ? 'est. ' : ''}${_dashDate(nc.date)}${nc.label ? ' · ' + esc(nc.label) : ''}` : 'Not scheduled') +
    card('Next payout', np && np.amount != null ? fmt$(np.amount) : '—', np && _dashDate(np.date) ? `${np.estimate ? 'est. ' : ''}${_dashDate(np.date)}` : 'Not scheduled') +
    card('Active circles', String(active), forming ? forming + ' forming' : 'none forming');
}

function renderDashCircles(D) {
  const el = document.getElementById('dashCircles'); if (!el) return;
  if (!D.ok.groups) { el.innerHTML = dashSectionError('circles'); return; }
  const prio = g => DASH_ACTIVE.includes(g.status) ? 0 : g.status === 'FORMING' ? 1 : 2;
  const list = D.groups.filter(g => DASH_ACTIVE.includes(g.status) || g.status === 'FORMING').sort((a, b) => prio(a) - prio(b)).slice(0, 4);
  const head = `<div class="dash-section-head"><h2>Your circles</h2>${list.length ? `<button type="button" class="link-btn" onclick="nav('groups')">View all circles</button>` : ''}</div>`;
  if (!list.length) { el.innerHTML = head + `<div class="empty"><p>You're not in any active circles yet.</p><div class="cluster" style="justify-content:center;margin-top:1rem"><button type="button" class="btn btn-primary" onclick="nav('discover')">Discover circles</button><button type="button" class="btn btn-ghost" onclick="nav('groups')">Create circle</button></div></div>`; return; }
  el.innerHTML = head + `<div class="circle-grid">${list.map(circleCardV2).join('')}</div>`;
}

function renderDashTimeline(D) {
  const el = document.getElementById('dashTimeline'); if (!el) return;
  const head = `<div class="dash-section-head"><h2>Upcoming</h2><button type="button" class="link-btn" onclick="nav('timeline')">Full timeline</button></div>`;
  if (!D.ok.tl) { el.innerHTML = head + dashInlineError(); return; }
  const t = D.tl || {}, events = [];
  if (t.next_contribution && t.next_contribution.due_date) { const nca = t.next_contribution.amount_cents; events.push({ date: t.next_contribution.due_date, label: 'Contribution due', sub: `${nca != null ? fmt$(nca) + ' · ' : ''}${esc(t.next_contribution.group_name || '')}`, state: 'pending' }); }
  const up = t.upcoming_payout, upDate = up && (up.date || up.payout_date || up.estimated_date), upAmt = up ? (up.amount_cents != null ? up.amount_cents : up.net_cents) : null;
  if (up && upDate) events.push({ date: upDate, label: 'Payout scheduled', sub: upAmt != null ? fmt$(upAmt) : '', state: up.date || up.payout_date ? 'active' : 'estimate' });
  if (D.sub && D.sub.is_premium && D.sub.current_period_end) events.push({ date: D.sub.current_period_end, label: 'Premium renews', sub: D.sub.price_cents != null ? fmt$(D.sub.price_cents) : '', state: 'active' });
  events.sort((a, b) => new Date(a.date) - new Date(b.date));
  const items = events.slice(0, 5);
  if (!items.length) { el.innerHTML = head + `<div class="empty"><p>Nothing scheduled yet.</p><div class="hint-muted">Contributions and payouts appear here once you're in an active circle.</div></div>`; return; }
  el.innerHTML = head + `<ol class="tl">${items.map(e => `<li class="tl-item"><span class="tl-dot status--${e.state === 'estimate' ? 'pending' : e.state}" aria-hidden="true"></span><div class="tl-body"><div class="tl-label">${e.label}</div><div class="tl-sub tnum">${e.sub}</div></div><time class="tl-date">${e.state === 'estimate' ? 'est. ' : ''}${_dashDate(e.date) || ''}</time></li>`).join('')}</ol>`;
}

function renderDashScore(D) {
  const el = document.getElementById('dashScore'); if (!el) return;
  if (!D.ok.trust) { el.innerHTML = dashCardError('SOL Score'); return; }
  const t = D.trust;
  if (!t || t.sol_score == null) { el.innerHTML = `<div class="side-card"><h3>SOL Score</h3><p class="hint-muted">Your score becomes available after your first circle activity. It reflects your on-platform reliability — not a credit score.</p><button type="button" class="btn btn-ghost btn--sm" onclick="nav('trust')">Learn more</button></div>`; return; }
  const max = t.max_score || 1000, pct = Math.max(0, Math.min(100, Math.round(t.sol_score / max * 100)));
  const band = pct >= 80 ? 'Excellent' : pct >= 60 ? 'Strong' : pct >= 40 ? 'Building' : 'New';
  const C = Math.PI * 52, off = C * (1 - pct / 100);
  el.innerHTML = `<div class="side-card score-card"><h3>SOL Score</h3>
    <div class="score-arc"><svg viewBox="0 0 120 72" width="130" height="78" aria-hidden="true"><path d="M8 66 A52 52 0 0 1 112 66" fill="none" stroke="var(--surface-2)" stroke-width="8" stroke-linecap="round"/><path d="M8 66 A52 52 0 0 1 112 66" fill="none" stroke="url(#scoreG)" stroke-width="8" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${off}"/><defs><linearGradient id="scoreG" x1="0" x2="1"><stop offset="0" stop-color="var(--sol-500)"/><stop offset="1" stop-color="var(--success-600)"/></linearGradient></defs></svg><div class="score-num tnum">${esc(t.sol_score)}</div></div>
    <div class="score-band">${band} · <span class="tnum">${esc(t.sol_score)}</span> of ${esc(max)}</div>
    <div class="hint-muted" style="font-size:.68rem;margin-bottom:.5rem">Reflects platform reliability, not a credit score.</div>
    <p class="sr-only">SOL Score ${esc(t.sol_score)} of ${esc(max)}, ${band}. Reflects platform reliability behaviour, not a credit score.</p>
    <button type="button" class="btn btn-ghost btn--sm" onclick="nav('trust')">View details</button></div>`;
}

function renderDashPremium(D) {
  const el = document.getElementById('dashPremium'); if (!el) return;
  if (!D.ok.sub) { el.innerHTML = dashCardError('Premium'); return; }
  const s = D.sub || {}, renew = s.current_period_end ? fmtDate(s.current_period_end) : null;
  let body;
  if (s.is_premium && s.cancel_at_period_end) body = `<span class="status status--warning">Cancellation scheduled</span><p class="hint-muted">Active through ${renew || 'the current period'}.</p><button type="button" class="btn btn-ghost btn--sm" onclick="nav('premium')">Manage</button>`;
  else if (s.is_premium) body = `<span class="status status--active">Active</span><p class="hint-muted">Renews ${renew || 'monthly'}.</p><button type="button" class="btn btn-ghost btn--sm" onclick="nav('premium')">Manage subscription</button>`;
  else body = `<div class="premium-price">${s.price_cents != null ? `<span class="tnum">${fmt$(s.price_cents)}</span><span class="premium-per">/month</span>` : `<span class="hint-muted">Price unavailable</span>`}</div><ul class="premium-benefits"><li>Enhanced circle recommendations</li><li>Advanced insights</li><li>Priority support</li></ul><button type="button" class="btn btn-primary btn--sm" onclick="nav('premium')">Go Premium</button>`;
  el.innerHTML = `<div class="side-card premium-card" role="group" aria-label="SOL Premium"><div class="premium-card__sheen" aria-hidden="true"></div><h3>SOL Premium</h3>${body}</div>`;
}

function renderDashGoals(D) {
  const el = document.getElementById('dashGoals'); if (!el) return;
  if (!D.ok.goals) { el.innerHTML = dashCardError('Goals'); return; }
  const active = (D.goals || []).filter(g => !['COMPLETED', 'CANCELLED', 'ACHIEVED'].includes(g.status))[0];
  if (!active) { el.innerHTML = `<div class="side-card"><h3>Savings goals</h3><p class="hint-muted">Set a target and track your progress toward it.</p><button type="button" class="btn btn-ghost btn--sm" onclick="nav('goals')">Create a goal</button></div>`; return; }
  const pct = active.progress_percent != null ? Math.round(active.progress_percent) : (active.target_cents ? Math.round((active.saved_cents || 0) / active.target_cents * 100) : 0);
  el.innerHTML = `<div class="side-card"><h3>Savings goal</h3><div class="goal-name">${esc(active.name)}</div><div class="pbar-row"><span class="tnum">${fmt$(active.saved_cents || 0)} of ${fmt$(active.target_cents || 0)}</span><span class="tnum">${Math.min(100, pct)}%</span></div><div class="pbar" role="progressbar" aria-valuenow="${Math.min(100, pct)}" aria-valuemin="0" aria-valuemax="100" aria-label="${esc(active.name)} savings progress"><div class="pbar__fill" style="width:${Math.min(100, pct)}%"></div></div>${active.target_date ? `<div class="hint-muted" style="margin-top:.4rem">Target ${fmtDate(active.target_date)}</div>` : ''}<button type="button" class="btn btn-ghost btn--sm" style="margin-top:.75rem" onclick="nav('goals')">View goals</button></div>`;
}

function renderDashTrust(D) {
  const el = document.getElementById('dashTrust'); if (!el) return;
  const idOK = dashIdVerified();
  const row = (state, text, act) => `<div class="trust-row"><span class="status status--${state}">${text}</span>${act ? `<button type="button" class="link-btn" onclick="${act.a}">${act.l}</button>` : ''}</div>`;
  const muted = text => `<div class="trust-row"><span class="hint-muted">${text}</span></div>`;
  let bankRow, payRow;
  if (!D.ok.banks) { bankRow = muted('Bank status unavailable'); payRow = muted('Payment readiness unavailable'); }
  else {
    const hasBank = (D.banks || []).length > 0, bankOK = (D.banks || []).some(b => b.verified), payOK = idOK && bankOK;
    bankRow = row(hasBank ? 'verified' : 'warning', hasBank ? 'Bank connected' : 'Connect bank', hasBank ? null : { a: "nav('bank')", l: 'Connect' });
    payRow = row(payOK ? 'verified' : 'pending', payOK ? 'Payments ready' : 'Action required', payOK ? null : { a: "nav('bank')", l: 'Finish' });
  }
  let alertRow;
  if (!D.ok.notes) alertRow = muted('Alerts unavailable');
  else { const unread = (D.notes || []).filter(n => !n.read_at).length; alertRow = row(unread ? 'pending' : 'verified', unread ? `${unread} unread alert${unread === 1 ? '' : 's'}` : 'No new alerts', unread ? { a: "nav('notifications')", l: 'View' } : null); }
  el.innerHTML = `<div class="side-card"><h3>Account status</h3>
    ${row(idOK ? 'verified' : 'warning', idOK ? 'Identity verified' : 'Verify identity', idOK ? null : { a: "nav('kyc')", l: 'Verify' })}
    ${bankRow}${payRow}${alertRow}
  </div>`;
}

function dashCardError(name) { return `<div class="side-card"><h3>${esc(name)}</h3><p class="hint-muted">Couldn't load this section.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadDashboard()">Retry</button></div>`; }
function dashSectionError(name) { return `<div class="dash-section-head"><h2>Your ${esc(name)}</h2></div><div class="empty"><p>Couldn't load your ${esc(name)}.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadDashboard()">Retry</button></div>`; }
function dashInlineError() { return `<div class="empty"><p>Couldn't load this section.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadDashboard()">Retry</button></div>`; }
function renderDashSkeletons() {
  const set = (id, html) => { const e = document.getElementById(id); if (e) e.innerHTML = html; };
  set('dashHero', `<div class="hero-copy"><span class="sk sk-line" style="width:38%;height:1.7rem"></span><span class="sk sk-line" style="width:72%"></span><div class="hero-stats"><span class="sk sk-block"></span><span class="sk sk-block"></span><span class="sk sk-block"></span></div></div><div class="hero-orb"><span class="sk" style="width:180px;height:180px;border-radius:50%;display:block"></span></div>`);
  set('dashAttention', `<div class="attn-card"><div class="attn-card__body"><span class="sk sk-line" style="width:40%"></span><span class="sk sk-line" style="width:65%"></span></div></div>`);
  set('dashSummary', Array.from({ length: 4 }).map(() => `<div class="sum-card"><span class="sk sk-line" style="width:60%"></span><span class="sk sk-line" style="width:45%;height:1.4rem"></span></div>`).join(''));
  set('dashCircles', `<div class="dash-section-head"><span class="sk sk-line" style="width:30%"></span></div><div class="circle-grid">${Array.from({ length: 2 }).map(() => `<div class="circle-card is-skeleton"><span class="sk sk-line" style="width:55%"></span><span class="sk sk-block"></span><span class="sk sk-line" style="width:70%"></span></div>`).join('')}</div>`);
  ['dashScore', 'dashPremium', 'dashGoals', 'dashTrust'].forEach(id => set(id, `<div class="side-card"><span class="sk sk-line" style="width:50%"></span><span class="sk sk-block" style="margin-top:.6rem"></span></div>`));
}

// ── SOL Orb — decorative Canvas-2D signature (no WebGL, no remote assets) ──────
const SolOrb = (function () {
  let cvs, ctx, raf = 0, t = 0, px = 0, py = 0, tx = 0, ty = 0, opts = { premium: false, progress: 0 }, moving = false;
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarse = () => matchMedia('(pointer: coarse)').matches;
  function draw() {
    if (!ctx) return;
    const w = cvs.width, h = cvs.height, cx = w / 2, cy = h / 2, r = w * 0.36;
    ctx.clearRect(0, 0, w, h);
    const a = t * 0.0004, lx = cx + Math.cos(a) * r * 0.55 + px * 12, ly = cy + Math.sin(a) * r * 0.55 + py * 12;
    const g = ctx.createRadialGradient(lx, ly, r * 0.08, cx, cy, r);
    g.addColorStop(0, opts.premium ? '#FFE7C0' : '#FBD9A2');
    g.addColorStop(0.55, opts.premium ? '#F4A93C' : '#E89324');
    g.addColorStop(1, opts.premium ? '#B4700F' : '#8A5316');
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fillStyle = g; ctx.fill();
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.lineWidth = 1.5; ctx.strokeStyle = 'rgba(255,255,255,.18)'; ctx.stroke();
    if (opts.progress > 0) {
      ctx.beginPath(); ctx.arc(cx, cy, r + 9, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * opts.progress);
      ctx.lineWidth = 4; ctx.lineCap = 'round'; ctx.strokeStyle = 'rgba(30,158,106,.85)'; ctx.stroke();
    }
  }
  function loop() { t += 16; px += (tx - px) * 0.06; py += (ty - py) * 0.06; draw(); raf = requestAnimationFrame(loop); }
  function onMove(e) { if (coarse() || !cvs) return; const b = cvs.getBoundingClientRect(); tx = ((e.clientX - b.left) / b.width - 0.5) * 2; ty = ((e.clientY - b.top) / b.height - 0.5) * 2; }
  function start() { if (raf || reduced() || document.hidden) return; if (!moving && !coarse()) { window.addEventListener('mousemove', onMove); moving = true; } loop(); }
  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; if (moving) { window.removeEventListener('mousemove', onMove); moving = false; } }
  const dashActive = () => { const p = document.getElementById('page-dashboard'); return !!(p && p.classList.contains('active')); };
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else if (cvs && dashActive()) start(); });
  return {
    render(o) { opts = Object.assign(opts, o || {}); cvs = document.getElementById('solOrb'); if (!cvs || !cvs.getContext) return; ctx = cvs.getContext('2d'); if (!ctx) return; stop(); draw(); start(); },
    stop, resume() { if (cvs && dashActive()) start(); },
  };
})();

// Return the next Date on which `day-of-month` occurs, starting from `from`.
// Example: from=Apr 22, day=1 -> May 1. from=Apr 22, day=25 -> Apr 25.
function _nextDayOfMonth(from, dayOfMonth) {
  const d = new Date(from.getFullYear(), from.getMonth(), dayOfMonth);
  if (d < from) d.setMonth(d.getMonth() + 1);
  return d;
}

// Consume a pending invite code stored from the landing page ?invite=... URL.
// Runs once per session — we clear the sessionStorage entry after the attempt
// so a second tab refresh doesn't loop-retry a rejected code.
async function consumePendingInvite() {
  const code = sessionStorage.getItem('sol_pending_invite');
  if (!code) return;
  sessionStorage.removeItem('sol_pending_invite');
  try {
    const g = await api('/groups/join-by-code', { method:'POST', body: JSON.stringify({ invite_code: code }) });
    if (g && g.id) showGroup(g.id);
  } catch (e) {
    // Soft-fail: user likely needs to finish KYC + bank first. Show a banner
    // on the dashboard with the code so they can paste it later on the
    // Circles page's "Join with invite code" form.
    const warn = document.createElement('div');
    warn.className = 'card';
    warn.style.cssText = 'max-width:none;margin-bottom:1rem;border-color:rgba(232,147,36,.3);background:rgba(232,147,36,.05)';
    warn.innerHTML = `<div style="font-weight:600;color:var(--gold);margin-bottom:.25rem">Invite pending</div>
      <div style="font-size:.85rem;color:var(--muted)">Couldn't auto-join (${esc((e.message || '').slice(0,80))}). Your invite code:
      <code style="color:var(--sol-600);background:var(--surface-2);padding:.15rem .4rem;border-radius:.3rem">${esc(code)}</code>.
      Finish verifying ID + linking a bank, then paste it into <button type="button" onclick="nav('groups')" style="background:none;border:0;padding:0;color:var(--sol-600);text-decoration:underline;cursor:pointer;font:inherit">Circles → Join with invite code</button>.</div>`;
    document.getElementById('dashAttention')?.after(warn);
  }
}

// ── Onboarding checklist ──────────────────────────────────────────────────────
// Shows 3 steps: Verify ID, Link bank, Verify bank. Hides once all complete.
async function loadOnboarding() {
  // The old dashboard onboarding checklist was replaced by the attention card +
  // account-status strip. Callers (bank/KYC flows) now just refresh the dashboard,
  // which recomputes those states. The legacy body below is inert (no #onboardingCard).
  if (!document.getElementById('onboardingCard')) { loadDashboard(); return; }
  const card = document.getElementById('onboardingCard');
  if (!card) return;
  let banks = [];
  try { banks = await api('/bank/list'); } catch { banks = []; }

  const kycDone = me?.kyc_status === 'VERIFIED';
  const hasBank = banks.length > 0;
  const hasVerifiedBank = banks.some(b => b.verified);
  const steps = [
    {
      id: 'kyc',
      done: kycDone,
      title: 'Verify your identity',
      sub: kycDone ? 'Identity verified.' : 'Submit basic details so we can protect every circle member.',
      cta: 'Verify ID',
      page: 'kyc',
    },
    {
      id: 'bank',
      done: hasBank,
      title: 'Link a bank account',
      sub: hasBank ? 'Bank linked.' : 'Connect your bank for contributions and payouts.',
      cta: 'Link bank',
      page: 'bank',
    },
    {
      id: 'verify',
      done: hasVerifiedBank,
      title: 'Verify your bank',
      sub: hasVerifiedBank ? 'Bank verified and ready.' :
           (hasBank ? 'Enter the two micro-deposits Sol sent to your bank.' : 'Requires a linked bank first.'),
      cta: 'Verify bank',
      page: 'bank',
    },
  ];

  const completed = steps.filter(s => s.done).length;
  if (completed === steps.length) { card.style.display = 'none'; return; }
  card.style.display = '';
  document.getElementById('onbProgress').textContent = `${completed} of ${steps.length}`;

  for (const s of steps) {
    const el = document.getElementById('onbStep-' + s.id);
    const icon = s.done
      ? '<span style="color:var(--green);font-weight:700">✓</span>'
      : '<span style="color:var(--muted);font-weight:700">○</span>';
    const ctaBtn = s.done ? '' :
      `<button type="button" class="btn btn-ghost" style="font-size:.75rem;padding:.35rem .75rem" onclick="nav('${s.page}')">${s.cta} →</button>`;
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:.75rem;padding:.6rem .75rem;background:rgba(14,23,38,.04);border-radius:.5rem;opacity:${s.done ? 0.6 : 1}">
        <div style="font-size:1.1rem;width:1.5rem;text-align:center">${icon}</div>
        <div style="flex:1;min-width:0">
          <div style="font-size:.9rem;font-weight:${s.done ? 500 : 600};${s.done ? 'text-decoration:line-through' : ''}">${s.title}</div>
          <div style="font-size:.75rem;color:var(--muted)">${s.sub}</div>
        </div>
        ${ctaBtn}
      </div>
    `;
  }
}
