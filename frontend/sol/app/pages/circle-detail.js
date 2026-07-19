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

    // Cycle status card (shown when group is active and has a cycle)
    let cycleSection = '';
    if (cycle && ['COLLECTING','SETTLING','ACTIVE'].includes(g.status)) {
      const paid = cycle.total_collected_cents / g.contribution_cents;
      const pct = Math.min(100, Math.round(paid / g.max_members * 100));
      const isRecipient = cycle.recipient_id === me?.id;
      const myPaymentHtml = myLatestPayment
        ? `<div style="margin-top:.75rem;display:flex;align-items:center;gap:.75rem">
            <span style="font-size:.8rem;color:var(--muted)">My contribution:</span>
            ${statusChip(myLatestPayment.status)} <span style="font-size:.8rem">${fmt$(myLatestPayment.amount_cents)}</span>
            ${myLatestPayment.next_retry_at ? `<span style="font-size:.75rem;color:var(--gold)">retry ${new Date(myLatestPayment.next_retry_at).toLocaleString()}</span>` : ''}
          </div>`
        : '';
      const recipientBanner = isRecipient
        ? `<div style="margin-top:1rem;padding:.75rem 1rem;background:rgba(232,147,36,.08);border:1px solid rgba(232,147,36,.3);border-radius:.5rem;color:var(--gold);font-size:.875rem">★ You are this cycle's payout recipient — ${fmt$(Math.round(g.contribution_cents * g.max_members * (1 - (g.fee_bps || 0) / 10000)))} net will be sent to your bank.</div>`
        : '';
      cycleSection = `<div class="card" style="max-width:none;margin-bottom:1.5rem">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:.5rem;margin-bottom:.75rem">
          <div style="font-weight:600">Cycle ${cycle.cycle_number}</div>${statusChip(cycle.status)}
        </div>
        <div style="background:var(--surface-2);border-radius:.5rem;height:8px;overflow:hidden;margin-bottom:.4rem">
          <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,var(--sol-400),var(--success-600));transition:.4s"></div>
        </div>
        <div style="font-size:.75rem;color:var(--muted)">${Math.round(paid)} of ${g.max_members} contributions collected</div>
        ${myPaymentHtml}${recipientBanner}
      </div>`;
    }

    // Invite section — only shows if this user is a member + circle has an
    // invite_code populated. Builds a shareable URL that lands on the join
    // page (see index.html ?invite=... handling).
    const inviteUrl = g.invite_code
      ? `${window.location.origin}/sol/?invite=${encodeURIComponent(g.invite_code)}`
      : '';
    const privacyBadge = g.is_private
      ? '<span class="badge badge-gold" style="font-size:.7rem">🔒 Private</span>'
      : '';
    const inviteSection = (isMember && g.invite_code && g.status === 'FORMING') ? `
      <div class="card" style="max-width:none;margin-bottom:1.5rem;border-color:rgba(232,147,36,.25);background:linear-gradient(135deg,rgba(232,147,36,.05),rgba(201,120,31,.04))">
        <div style="font-weight:600;margin-bottom:.25rem">Invite your friends</div>
        <div style="font-size:.8rem;color:var(--muted);margin-bottom:.75rem">Share this link — only people with it can ${g.is_private ? 'find and ' : ''}join.</div>
        <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
          <input readonly value="${inviteUrl}" id="inviteUrl-${g.id}" style="flex:1;min-width:200px;background:var(--surface-2);border:1px solid var(--line);border-radius:.5rem;padding:.5rem .7rem;color:var(--ink-900);font-size:.8rem;font-family:monospace">
          <button type="button" class="btn btn-primary" style="font-size:.8rem;padding:.45rem 1rem" onclick="copyInvite('${g.id}')">Copy</button>
        </div>
        <div style="font-size:.7rem;color:var(--muted);margin-top:.5rem">Code: <code style="color:var(--sol-600)">${esc(g.invite_code)}</code></div>
      </div>
    ` : '';

    el.innerHTML = `
      <div class="card" style="max-width:none;margin-bottom:1.5rem">
        <div style="display:flex;align-items:start;justify-content:space-between;gap:.5rem;margin-bottom:1rem">
          <h2 style="font-size:1.25rem">${esc(g.name)} ${privacyBadge}</h2>${statusChip(g.status)}
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:${canJoin?'1.5rem':'0'}">
          <div><div style="font-size:.72rem;color:var(--muted)">Contribution</div><div style="font-weight:600">${fmt$(g.contribution_cents)}</div></div>
          <div><div style="font-size:.72rem;color:var(--muted)">Payout to recipient</div><div style="font-weight:600">${fmt$(Math.round(g.contribution_cents * g.max_members * (1 - (g.fee_bps || 0) / 10000)))}</div><div style="font-size:.68rem;color:var(--muted)">after ${(g.fee_bps || 0) / 100}% platform fee</div></div>
          <div><div style="font-size:.72rem;color:var(--muted)">Members</div><div style="font-weight:600">${members.length} / ${g.max_members}</div></div>
          <div><div style="font-size:.72rem;color:var(--muted)">Cycle</div><div style="font-weight:600">${g.current_cycle_number}</div></div>
          <div><div style="font-size:.72rem;color:var(--muted)">Fee</div><div style="font-weight:600">${g.fee_bps/100}%</div></div>
        </div>
        ${canJoin ? (() => {
          // Payout preview: if user joins now, they'd be position (members.length + 1).
          // Net payout = pool minus the platform fee (fee_bps, disclosed dynamically below).
          const yourPosition = members.length + 1;
          const feePct = (g.fee_bps || 0) / 100;
          const netPayout = Math.round(g.contribution_cents * g.max_members * (1 - (g.fee_bps || 0) / 10000));
          const totalContributions = g.contribution_cents * g.max_members;
          const moneyOverTime = '<strong>$' + (netPayout/100).toLocaleString('en-US',{minimumFractionDigits:2}) + '</strong>';
          return `
            <div style="background:rgba(232,147,36,.07);border:1px solid rgba(232,147,36,.25);border-radius:.6rem;padding:.9rem 1rem;margin-bottom:1rem;font-size:.85rem">
              <div style="color:var(--sol-600);font-weight:600;margin-bottom:.3rem">Join preview</div>
              <div style="color:var(--ink-900);margin-bottom:.2rem">You'd be position <strong style="color:var(--sol-600)">${yourPosition}</strong> of ${g.max_members} in the payout rotation.</div>
              <div style="color:var(--muted);font-size:.8rem">You'll contribute ${fmt$(g.contribution_cents)} each cycle for ${g.max_members} cycles (total ${fmt$(totalContributions)}) and receive ${moneyOverTime} on cycle ${yourPosition} (${feePct}% platform fee applied).</div>
            </div>
            <button class="btn btn-primary" id="joinBtn" onclick="joinGroup('${g.id}')">Join this circle</button>
            <p class="err" id="joinErr" style="display:none"></p>
          `;
        })() : ''}
      </div>
      ${inviteSection}
      ${cycleSection}
      <h3 style="margin-bottom:.75rem">Members</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Position</th><th>Member</th><th>Status</th><th>Payout received</th></tr></thead>
          <tbody>
            ${members.length ? members.map(m => `
              <tr style="${m.user_id===me.id?'background:rgba(232,147,36,.06)':''}">
                <td>${m.position ?? '—'}</td>
                <td>${m.user_id===me.id?'<span style="color:var(--sol-600)">You</span>':'<span style="color:var(--muted)">SOL member</span>'}</td>
                <td>${statusChip(m.status)}</td>
                <td style="color:${m.has_received_payout?'var(--green)':'var(--muted)'}">${m.has_received_payout?'✓ Yes':'—'}</td>
              </tr>`).join('') : '<tr><td colspan="4" class="empty">No members yet</td></tr>'}
          </tbody>
        </table>
      </div>`;
  } catch (e) { el.innerHTML = `<div class="empty"><p>Couldn't load this circle.</p><button type="button" class="btn btn-ghost btn--sm" onclick="nav('groups')">Back to circles</button></div>`; }
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
