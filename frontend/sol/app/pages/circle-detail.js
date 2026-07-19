// SOL member app — pages/circle-detail.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Group detail ──────────────────────────────────────────────────────────────
async function showGroup(id) {
  nav('group-detail');
  const el = document.getElementById('groupDetail');
  el.innerHTML = '<div class="spinner"></div>';
  try {
    // members embedded in group response — no separate /members call needed
    const [g, myPayments] = await Promise.all([
      api(`/groups/${id}`),
      api(`/groups/${id}/my-payments`).catch(() => []),
    ]);
    const members = g.members || [];
    const isMember = members.some(m => m.user_id === me.id);
    const canJoin = g.status === 'FORMING' && !isMember;
    const cycle = g.current_cycle;
    const myLatestPayment = myPayments[0] || null;
    // Money math (unchanged): net payout = full pool minus the disclosed platform fee.
    const feePct = (g.fee_bps || 0) / 100;
    const netPayout = Math.round(g.contribution_cents * g.max_members * (1 - (g.fee_bps || 0) / 10000));
    // Private indicator — the design-system marker (was the legacy .badge-gold pill).
    const privMark = g.is_private ? ' <span title="Private" aria-label="Private">🔒</span>' : '';

    // Cycle status card (shown when group is active and has a cycle)
    let cycleSection = '';
    if (cycle && ['COLLECTING','SETTLING','ACTIVE'].includes(g.status)) {
      const paid = g.contribution_cents ? cycle.total_collected_cents / g.contribution_cents : 0;
      const pct = g.max_members ? Math.min(100, Math.round(paid / g.max_members * 100)) : 0;
      const isRecipient = cycle.recipient_id === me?.id;
      const myPaymentHtml = myLatestPayment
        ? `<div class="cdetail__mypay"><span class="hint-muted">My contribution:</span>${statusChip(myLatestPayment.status)} <span>${fmt$(myLatestPayment.amount_cents)}</span>${myLatestPayment.next_retry_at ? `<span class="cdetail__retry">retry ${esc(new Date(myLatestPayment.next_retry_at).toLocaleString())}</span>` : ''}</div>`
        : '';
      const recipientBanner = isRecipient
        ? `<div class="cdetail__recipient">★ You are this cycle's payout recipient — ${fmt$(netPayout)} net will be sent to your bank.</div>`
        : '';
      cycleSection = `<div class="card cdetail__cycle">
        <div class="cdetail__cycle-head"><div class="cdetail__cycle-title">Cycle ${esc(cycle.cycle_number)}</div>${statusChip(cycle.status)}</div>
        <div class="pbar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="Contributions collected this cycle"><div class="pbar__fill" style="width:${pct}%"></div></div>
        <div class="cdetail__cycle-meta">${Math.round(paid)} of ${esc(g.max_members)} contributions collected</div>
        ${myPaymentHtml}${recipientBanner}
      </div>`;
    }

    // Invite section — only shows if this user is a member + circle has an
    // invite_code populated. Builds a shareable URL that lands on the join
    // page (see index.html ?invite=... handling).
    const inviteUrl = g.invite_code
      ? `${window.location.origin}/sol/?invite=${encodeURIComponent(g.invite_code)}`
      : '';
    const inviteSection = (isMember && g.invite_code && g.status === 'FORMING') ? `
      <div class="card cdetail__invite">
        <div class="cdetail__invite-title">Invite your friends</div>
        <div class="cdetail__invite-sub">Share this link — only people with it can ${g.is_private ? 'find and ' : ''}join.</div>
        <div class="cdetail__invite-row">
          <input readonly value="${esc(inviteUrl)}" id="inviteUrl-${esc(g.id)}" class="cdetail__invite-input">
          <button type="button" class="btn btn-primary btn--sm" onclick="copyInvite('${esc(g.id)}')">Copy</button>
        </div>
        <div class="cdetail__invite-code">Code: <code>${esc(g.invite_code)}</code></div>
      </div>
    ` : '';

    el.innerHTML = `
      <div class="card">
        <div class="cdetail__head"><h2 class="cdetail__title">${esc(g.name)}${privMark}</h2>${statusChip(g.status)}</div>
        <div class="cdetail__figs${canJoin ? ' cdetail__figs--join' : ''}">
          <div><div class="fig-label">Contribution</div><div class="fig-val tnum">${fmt$(g.contribution_cents)}</div></div>
          <div><div class="fig-label">Payout to recipient</div><div class="fig-val tnum">${fmt$(netPayout)}</div><div class="hint-muted">after ${feePct}% platform fee</div></div>
          <div><div class="fig-label">Members</div><div class="fig-val tnum">${esc(members.length)} / ${esc(g.max_members)}</div></div>
          <div><div class="fig-label">Cycle</div><div class="fig-val tnum">${esc(g.current_cycle_number)}</div></div>
          <div><div class="fig-label">Fee</div><div class="fig-val tnum">${feePct}%</div></div>
        </div>
        ${canJoin ? (() => {
          // Payout preview: if user joins now, they'd be position (members.length + 1).
          const yourPosition = members.length + 1;
          const totalContributions = g.contribution_cents * g.max_members;
          return `
            <div class="cdetail__callout">
              <div class="cdetail__callout-title">Join preview</div>
              <div>You'd be position <strong class="cdetail__pos">${yourPosition}</strong> of ${esc(g.max_members)} in the payout rotation.</div>
              <div class="cdetail__callout-sub">You'll contribute ${fmt$(g.contribution_cents)} each cycle for ${esc(g.max_members)} cycles (total ${fmt$(totalContributions)}) and receive <strong>${fmt$(netPayout)}</strong> on cycle ${yourPosition} (${feePct}% platform fee applied).</div>
            </div>
            <button class="btn btn-primary" id="joinBtn" onclick="joinGroup('${esc(g.id)}')">Join this circle</button>
            <p class="err" id="joinErr" style="display:none"></p>
          `;
        })() : ''}
      </div>
      ${inviteSection}
      ${cycleSection}
      <h3 class="cdetail__members-title">Members</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Position</th><th>Member</th><th>Status</th><th>Payout received</th></tr></thead>
          <tbody>
            ${members.length ? members.map(m => `
              <tr class="${m.user_id===me.id?'cdetail__member-you':''}">
                <td>${m.position ?? '—'}</td>
                <td>${m.user_id===me.id?'<span class="cdetail__member-me">You</span>':'<span class="cdetail__member-other">SOL member</span>'}</td>
                <td>${statusChip(m.status)}</td>
                <td class="${m.has_received_payout?'cdetail__payout-yes':'cdetail__member-other'}">${m.has_received_payout?'✓ Yes':'—'}</td>
              </tr>`).join('') : '<tr><td colspan="4" class="empty">No members yet</td></tr>'}
          </tbody>
        </table>
      </div>`;
  } catch (e) { if (_aborted(e)) return; el.innerHTML = `<div class="empty"><p>Couldn't load this circle.</p><button type="button" class="btn btn-ghost btn--sm" onclick="nav('groups')">Back to circles</button></div>`; }
}

async function joinGroup(id) {
  const btn = document.getElementById('joinBtn');
  const err = document.getElementById('joinErr');
  err.style.display = 'none';
  btn.disabled = true; btn.textContent = 'Joining…';
  try {
    await api(`/groups/${id}/join`, { method:'POST' });
    showGroup(id);
  } catch(e) {
    // Translate backend error messages to actionable guidance + deep-link
    let msg = e.message || 'Failed to join';
    let cta = '';
    const linkStyle = 'background:none;border:0;padding:0;color:var(--sol-600);text-decoration:underline;cursor:pointer;font:inherit';
    if (/no active bank/i.test(msg) || /bank account/i.test(msg)) {
      msg = 'You need a verified bank account before joining a circle.';
      cta = ` <button type="button" onclick="nav('bank')" style="${linkStyle}">Go to Bank →</button>`;
    } else if (/kyc/i.test(msg)) {
      msg = 'Complete identity verification first.';
      cta = ` <button type="button" onclick="nav('kyc')" style="${linkStyle}">Verify ID →</button>`;
    } else if (/account status/i.test(msg)) {
      msg = 'Your account is not active. Please contact support.';
    }
    // esc(msg): matched branches are static, but the fall-through path carries the
    // raw backend message — escape it. cta is controlled static HTML (kept raw).
    err.innerHTML = esc(msg) + cta;
    err.style.display = 'block';
    btn.disabled = false; btn.textContent = 'Join this circle';
  }
}
