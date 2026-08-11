// ============================================================================
// Panel: security (workspace) — SECURITY COMMAND CENTER (Increment 15)
// Big posture score over a large meter (warn <75 / crit <50) · Critical/High/
// Medium/Low count row · six-check status list · a drill-down of sample findings
// that reveal evidence → affected component → remediation → status.
// Live via data:security.
//
// SECURITY: every snapshot value reaches the DOM through textContent only.
// innerHTML is never used with interpolated data. The findings list is a static
// literal catalog (non-sensitive) built once; only the score/counts/checks block
// re-renders on each snapshot.
// ============================================================================

import { dataFreshness } from '../shared/dataFreshness.js';

// Static, non-sensitive sample findings. Literals only — never snapshot data.
const FINDINGS = [
  {
    sev: 'HIGH',
    title: 'Vulnerable transitive dependency (prototype pollution)',
    evidence: 'lodash@4.17.19 flagged by advisory GHSA-p6mc-4-node; reachable from the billing worker.',
    component: 'billing-worker · package-lock.json',
    remediation: 'Bump lodash to 4.17.21, regenerate the lockfile, and re-run the dependency audit gate.',
    status: 'Open · assigned to platform',
  },
  {
    sev: 'MEDIUM',
    title: 'Session cookie missing SameSite attribute',
    evidence: 'Set-Cookie on POST /auth/login omits SameSite; only Secure is present.',
    component: 'api-gateway · auth middleware',
    remediation: 'Set SameSite=Lax (or Strict) alongside Secure and HttpOnly on all session cookies.',
    status: 'In review',
  },
  {
    sev: 'LOW',
    title: 'Verbose error page leaks stack frames in staging',
    evidence: 'A 500 on /reports/export returned a full Python traceback in the response body.',
    component: 'reports-service (staging)',
    remediation: 'Disable debug rendering outside dev; return a generic 500 body and log server-side only.',
    status: 'Acknowledged',
  },
];

export function create(ctx) {
  const { bus, data, el, avatar, sound } = ctx;
  const off = [];

  const num = v => Math.max(0, Math.round(Number(v) || 0));
  const clampScore = v => Math.max(0, Math.min(100, Math.round(Number(v) || 0)));

  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const kicker = text => {
    const d = mk('div', 'dim', text);
    d.style.cssText = 'font-size:var(--fs-micro);letter-spacing:var(--tracking-wide);text-transform:uppercase';
    return d;
  };

  el.replaceChildren();

  // — Live block (score · counts · checks): rebuilt on every snapshot ---------
  const live = mk('div');
  live.style.cssText = 'display:flex;flex-direction:column;gap:var(--s5);margin-bottom:var(--s6)';
  el.appendChild(live);

  // status → glyph + colour class for the check list.
  const checkMark = st =>
    st === 'ok'   ? ['✓', 'ok']    // ✓
    : st === 'crit' ? ['✕', 'crit'] // ✕
    :                 ['!', 'warn']; // !

  // score → posture verdict (thresholds match the meter classes).
  const verdict = s =>
    s < 50 ? { cls: 'crit', meter: 'meter crit', word: 'CRITICAL EXPOSURE' }
    : s < 75 ? { cls: 'warn', meter: 'meter warn', word: 'ELEVATED RISK' }
    :          { cls: 'acc',  meter: 'meter',      word: 'SECURE POSTURE' };

  const CHECKS = [
    ['Authentication', 'authentication'],
    ['Secrets', 'secrets'],
    ['Dependencies', 'dependencies'],
    ['Infrastructure', 'infrastructure'],
    ['Payments', 'payments'],
    ['Agents', 'agents'],
  ];
  const COUNTS = [
    ['Critical', 'critical', 'crit'],
    ['High', 'high', 'warn'],
    ['Medium', 'medium', 'acc'],
    ['Low', 'low', 'dim'],
  ];

  function renderLive(snap) {
    const s = snap || {};
    const score = clampScore(s.score);
    const vd = verdict(score);
    live.replaceChildren();

    // Score header + big number + verdict word.
    const head = mk('div');
    head.style.cssText = 'display:flex;align-items:baseline;gap:var(--s3);flex-wrap:wrap';
    head.appendChild(kicker('SECURITY POSTURE'));
    head.appendChild(dataFreshness.badge('security'));
    const big = mk('span', 'big mono ' + vd.cls, String(score));
    const outOf = mk('span', 'dim mono', '/ 100');
    outOf.style.fontSize = 'var(--fs-sm)';
    const word = mk('span', vd.cls, vd.word);
    word.style.cssText = 'margin-left:auto;font-size:var(--fs-tiny);letter-spacing:var(--tracking-wide);text-transform:uppercase';
    head.append(big, outOf, word);

    const meter = mk('div', vd.meter);
    meter.style.height = '12px';
    const fill = mk('i');
    fill.style.width = score + '%';
    meter.appendChild(fill);

    const scoreWrap = mk('div');
    scoreWrap.style.cssText = 'display:flex;flex-direction:column;gap:var(--s2)';
    scoreWrap.append(head, meter);
    live.appendChild(scoreWrap);

    // Severity count row.
    const counts = mk('div');
    counts.style.cssText = 'display:grid;grid-template-columns:repeat(4,1fr);gap:var(--s3)';
    for (const [label, key, col] of COUNTS) {
      const card = mk('div', 'kpi');
      card.style.cssText = 'background:var(--bg-raised);border:1px solid var(--stroke);border-radius:var(--r-md);padding:var(--s3)';
      card.appendChild(mk('div', 'lbl', label));
      const v = mk('div', 'big mono ' + col, String(num(s[key])));
      v.style.fontSize = 'var(--fs-xl)';
      card.appendChild(v);
      counts.appendChild(card);
    }
    live.appendChild(counts);

    // Six-check status list.
    const checks = s.checks || {};
    const checkWrap = mk('div');
    checkWrap.appendChild(kicker('CONTROL CHECKS'));
    const listCard = mk('div');
    listCard.style.cssText = 'margin-top:var(--s2);background:var(--bg-raised);border:1px solid var(--stroke);border-radius:var(--r-md);padding:0 var(--s3)';
    for (const [label, key] of CHECKS) {
      const st = checks[key];
      const [glyph, col] = checkMark(st);
      const row = mk('div', 'row');
      row.appendChild(mk('span', 'k', label));
      const v = mk('span', 'v ' + col);
      v.append(mk('span', null, glyph), document.createTextNode('  '), mk('span', 'dim', String(st || 'n/a').toUpperCase()));
      row.appendChild(v);
      listCard.appendChild(row);
    }
    checkWrap.appendChild(listCard);
    live.appendChild(checkWrap);
  }

  // — Findings drill-down: static, built once ---------------------------------
  // map severity → a real CSS custom property (not a class name) so
  // var(--…) resolves for all four levels, incl. MEDIUM/LOW.
  const sevClass = sev =>
    sev === 'CRITICAL' ? 'crit' : sev === 'HIGH' ? 'warn' : sev === 'MEDIUM' ? 'accent-ink' : 'ink-mute';

  function findingRow(key, value) {
    const row = mk('div', 'row');
    row.appendChild(mk('span', 'k', key));
    const v = mk('span', 'v');
    v.style.cssText = 'white-space:normal;text-align:right;max-width:70%;font-family:var(--font)';
    v.textContent = value;
    row.appendChild(v);
    return row;
  }

  function buildFindings() {
    const wrap = mk('div');
    wrap.appendChild(kicker('FINDINGS'));

    const list = mk('div');
    list.style.marginTop = 'var(--s2)';

    for (const f of FINDINGS) {
      const item = mk('div');
      item.style.borderBottom = '1px solid var(--stroke-soft)';

      const btn = mk('button');
      btn.type = 'button';
      btn.setAttribute('aria-expanded', 'false');
      btn.style.cssText = 'display:flex;align-items:center;gap:var(--s2);width:100%;text-align:left;padding:var(--s3) 0';

      const caret = mk('span', 'dim mono', '▸');
      caret.style.cssText = 'flex:none;font-size:var(--fs-tiny);transition:transform var(--t-fast) var(--ease)';

      const sev = mk('span', 'chip');
      sev.style.flex = 'none';
      sev.style.color = 'var(--' + sevClass(f.sev) + ')';
      sev.style.borderColor = 'var(--' + sevClass(f.sev) + ')';
      sev.append(mk('span', 'd'), mk('span', null, f.sev));

      const title = mk('span', null, f.title);
      title.style.cssText = 'flex:1;font-size:var(--fs-sm);color:var(--ink);line-height:1.35';

      btn.append(caret, sev, title);

      const reveal = mk('div');
      reveal.style.cssText = 'overflow:hidden;max-height:0;transition:max-height var(--t-med) var(--ease)';
      const inner = mk('div');
      inner.style.cssText = 'padding:0 0 var(--s3) var(--s5)';
      inner.append(
        findingRow('Finding', f.title),
        findingRow('Evidence', f.evidence),
        findingRow('Affected', f.component),
        findingRow('Remediation', f.remediation),
        findingRow('Status', f.status),
      );
      reveal.appendChild(inner);

      let open = false;
      btn.addEventListener('click', () => {
        open = !open;
        reveal.style.maxHeight = open ? reveal.scrollHeight + 'px' : '0';
        caret.style.transform = open ? 'rotate(90deg)' : 'none';
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (open) {
          sound && sound.cue && sound.cue('tick');
          avatar && avatar.litHalo && avatar.litHalo('security');
        }
      });

      item.append(btn, reveal);
      list.appendChild(item);
    }

    wrap.appendChild(list);
    return wrap;
  }

  // Initial paint from the current snapshot, then stay live.
  renderLive(data && data.get ? data.get('security') : null);
  el.appendChild(buildFindings());
  avatar && avatar.litHalo && avatar.litHalo('security');
  off.push(bus.on('data:security', renderLive));

  return { destroy() { off.forEach(f => f && f()); } };
}
