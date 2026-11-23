// SOL member app — pages/onboarding.js
// Classic script (shared global scope); loaded in order by app.html.
//
// First-run guide: a SolDialog with four short steps, opened on the first dashboard load
// after sign-in and from Settings > How MySol works. "Seen" is remembered per member id in
// localStorage (SolAccount.guideSeen/markGuideSeen), the record across visits, and in this
// page's memory for the page session. So when storage is blocked nothing throws, the guide
// opens once in the page session, and it may show again on a later visit. Escape and the close
// button dismiss it; focus returns to the page heading.

const GUIDE_STEPS = [
  {
    title: 'What a sol is',
    body: `<p>A sol is a savings circle. A small group agrees to save together on a set schedule.</p>
      <p>Each cycle, every member puts in money and one member receives the whole pot. MySol keeps track of who has paid and whose turn it is.</p>`,
  },
  {
    title: 'How a cycle works',
    body: `<ul class="guide__list">
        <li>Everyone pays the same amount each cycle.</li>
        <li>One member receives the pot that cycle.</li>
        <li>The order is set in the circle, so each member's turn is known.</li>
        <li>The circle ends when every member has received the pot once.</li>
      </ul>`,
  },
  {
    title: 'What MySol checks',
    body: `<ul class="guide__list">
        <li>We check your identity before you join a circle.</li>
        <li>We verify your bank account with two small test deposits.</li>
        <li>We pay out only after contributions have settled at the bank.</li>
      </ul>`,
  },
  {
    title: 'What to do next',
    body: `<p>Get ready to join your first circle:</p>
      <ul class="guide__actions">
        <li><button type="button" class="btn btn-ghost btn--sm" data-guide-go="settings" onclick="guideGo('settings')">Verify your email</button></li>
        <li><button type="button" class="btn btn-ghost btn--sm" data-guide-go="kyc" onclick="guideGo('kyc')">Check your ID</button></li>
        <li><button type="button" class="btn btn-ghost btn--sm" data-guide-go="bank" onclick="guideGo('bank')">Link a bank</button></li>
        <li><button type="button" class="btn btn-primary btn--sm" data-guide-go="discover" onclick="guideGo('discover')">Join or create a circle</button></li>
      </ul>`,
  },
];
let _guideStep = 0;
// Member ids whose guide opened in this page session (the in-memory "seen").
const _guideShownIds = new Set();

// The active page's heading, focusable (tabindex -1) so focus can return to it.
function _activeHeading() {
  const page = document.querySelector('.page.active');
  const h = page ? page.querySelector('h1') : null;
  if (h && !h.hasAttribute('tabindex')) h.setAttribute('tabindex', '-1');
  return h;
}

function renderGuide() {
  const s = GUIDE_STEPS[_guideStep];
  const last = _guideStep === GUIDE_STEPS.length - 1;
  const set = (id, fn) => { const el = document.getElementById(id); if (el) fn(el); };
  set('guideTitle', el => { el.textContent = s.title; });
  set('guideBody', el => { el.innerHTML = s.body; });   // static markup above, no server data
  set('guideStepCount', el => { el.textContent = `Step ${_guideStep + 1} of ${GUIDE_STEPS.length}`; });
  set('guideBack', el => { el.hidden = _guideStep === 0; });
  set('guideNext', el => { el.hidden = last; });
  set('guideDone', el => { el.hidden = !last; });
}

// Open the guide at its first step. Focus returns to the active page's heading on close.
function openGuide() {
  if (!document.getElementById('guideDialog')) return;
  _guideStep = 0;
  renderGuide();
  SolDialog.open('guideDialog', { opener: _activeHeading() || document.activeElement, initialFocus: '#guideNext' });
}
function closeGuide() { SolDialog.close('guideDialog'); }

function guideStep(delta) {
  const next = Math.max(0, Math.min(GUIDE_STEPS.length - 1, _guideStep + delta));
  if (next === _guideStep) return;
  _guideStep = next;
  renderGuide();
  // Keep focus on a visible control: Next while there is one, else the step's title.
  const n = document.getElementById(delta > 0 ? 'guideNext' : 'guideBack');
  const target = n && !n.hidden ? n : document.getElementById('guideTitle');
  if (target) { try { target.focus(); } catch (e) {} }
}

// A "what to do next" button: close the guide, then go there (nav() moves focus to that
// page's heading).
function guideGo(page) {
  SolDialog.close('guideDialog', { restoreFocus: false });
  nav(page);
}

// Called at the end of loadDashboard(): the first dashboard load for this member opens the
// guide, once. Not while another dialog is open or another page is showing.
function maybeShowGuide() {
  if (!me || !me.id) return;
  const dash = document.getElementById('page-dashboard');
  if (!dash || !dash.classList.contains('active')) return;
  if (document.querySelector('.bank-modal.is-open, .more-sheet-backdrop.open')) return;
  if (_guideShownIds.has(me.id)) return;   // already opened in this page session
  const storage = SolAccount.storageOf(window);
  if (SolAccount.guideSeen(storage, me.id)) return;
  _guideShownIds.add(me.id);
  SolAccount.markGuideSeen(storage, me.id);
  openGuide();
}
