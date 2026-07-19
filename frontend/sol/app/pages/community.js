// SOL member app — pages/community.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ═══ Community feed ═══════════════════════════════════════════════════════════
// Backend truth (app/{api,services}/community.py):
//   GET  /feed?limit&offset → [{id, author_id, group_id, body, created_at}].
//        list_feed = global posts (group_id NULL) + posts from circles I'm an
//        ACTIVE member of, newest-first, hidden excluded. Access is enforced
//        server-side, so any circle post I receive is one I'm entitled to see —
//        but the payload carries NO circle name and NO author name (only UUIDs).
//   POST /feed {body}              → create a GLOBAL post (group_id omitted).
//   GET/POST /feed/{id}/comments   → list / add comments ({id,post_id,user_id,body,created_at}).
//   POST/DELETE /feed/{id}/like    → idempotent like → {liked, like_count}.
//   POST /community/report {target_type,target_id,reason} → review request.
// NOT supported (never faked): editing a post; member delete (hide is owner/admin
//   only — a regular member's delete would 403); an "official" flag on feed posts;
//   member-visible global announcements; multi-emoji reactions; profiles/DMs/follows.
// Author identity is ONLY "You" (author_id === me.id) or "SOL member" — the raw
// user_id is used solely for the self-comparison and is NEVER rendered. All post
// and comment bodies are escaped + rendered as plain text (white-space:pre-wrap).
const COMM_PAGE = 30;
const commState = { posts: [], filter: 'all', offset: 0, loading: false, more: false, likes: {}, open: {} };
let _commPostBusy = false; const _commLikeBusy = {}, _commCommentBusy = {};

function commAnnounce(msg) { const l = document.getElementById('commLive'); if (l) l.textContent = msg; }
function _commReduce() { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }

function commWhen(d) {
  const diff = Math.max(0, Date.now() - d.getTime()), min = 60000, hr = 3600000, day = 86400000;
  if (diff < min) return 'just now';
  if (diff < hr) return `${Math.floor(diff / min)}m ago`;
  if (diff < day) return `${Math.floor(diff / hr)}h ago`;
  if (diff < 7 * day) return `${Math.floor(diff / day)}d ago`;
  return fmtDate(d);
}

// Map one raw post → a safe view model. Returns null for a malformed item so the
// feed skips it rather than failing entirely.
function normalizeCommunityPost(p) {
  if (!p || typeof p !== 'object') return null;
  const ref = _isUuid(p.id) ? p.id : null;                    // uuid-validated action ref
  const body = typeof p.body === 'string' ? p.body : '';
  if (!ref || !body.trim()) return null;
  const myId = me && me.id;
  const mine = !!myId && p.author_id === myId;                // self-compare only; never rendered
  const created = p.created_at ? new Date(p.created_at) : null;
  const validDate = created && !isNaN(created.getTime());
  return {
    ref, body, mine,
    authorLabel: mine ? 'You' : 'SOL member',
    scope: p.group_id ? 'CIRCLE' : 'GENERAL',                 // only grounded category — no backend category field
    createdISO: validDate ? created.toISOString() : null,
    createdText: validDate ? commWhen(created) : null,
  };
}

function normalizeComment(c) {
  if (!c || typeof c !== 'object') return null;
  const ref = _isUuid(c.id) ? c.id : null;
  const body = typeof c.body === 'string' ? c.body : '';
  if (!ref || !body.trim()) return null;
  const myId = me && me.id;
  const mine = !!myId && c.user_id === myId;
  const created = c.created_at ? new Date(c.created_at) : null;
  const validDate = created && !isNaN(created.getTime());
  return { ref, body, mine, authorLabel: mine ? 'You' : 'SOL member',
    createdISO: validDate ? created.toISOString() : null, createdText: validDate ? commWhen(created) : null };
}

// Map any thrown api() error to a safe, generic member-facing message — never
// surface raw provider/moderation detail.
// safeError — the ONE app-wide mapper from a thrown api() error to a safe,
// generic member-facing message. Never surfaces a raw provider/technical string.
// Use for generic failure paths; pages with genuinely domain-specific guidance
// (e.g. join eligibility) may still map their own known cases first.
function safeError(e) {
  const m = String((e && e.message) || '').toLowerCase();
  if (m.includes('429') || m.includes('rate') || m.includes('too many') || m.includes('slow down')) return "You're doing that a lot — please wait a moment and try again.";
  if (m.includes('expired') || m.includes('session') || m.includes('sign in')) return 'Your session expired. Please sign in again.';
  if (m.includes('forbidden') || m.includes('permission') || m.includes('not a member') || m.includes('access')) return "You don't have access to do that.";
  if (m.includes('not found')) return 'That content is no longer available.';
  if (m.includes('4000') || m.includes('too long') || m.includes('at most')) return 'That message is too long.';
  return 'Something went wrong. Please try again.';
}

function commSkeleton() {
  return Array.from({ length: 3 }).map(() =>
    `<li class="comm-post"><span class="sk sk-line" style="width:28%"></span><span class="sk sk-block" style="margin-top:.6rem"></span></li>`).join('');
}

async function loadCommunity(reset) {
  const el = document.getElementById('feedList');
  if (!el) return;
  commState.offset = 0; commState.loading = true; commState.open = {}; commState.likes = {};
  el.innerHTML = commSkeleton();
  const lm = document.getElementById('commLoadMore'); if (lm) lm.style.display = 'none';
  // Best-effort refresh of `me` so "You"/"My posts" is accurate — never blocks the feed.
  if (!me || !me.id) { try { const m = await api('/auth/me'); if (m && m.id) me = m; } catch (_) {} }
  try {
    const raw = await api(`/feed?limit=${COMM_PAGE}&offset=0`);
    const list = Array.isArray(raw) ? raw : [];
    commState.posts = list.map(normalizeCommunityPost).filter(Boolean);
    commState.more = list.length >= COMM_PAGE;
    commState.offset = list.length;
    renderCommunity();
    if (reset) commAnnounce('Community feed refreshed.');
  } catch (e) {
    commState.posts = [];
    el.innerHTML = `<li class="notif-empty"><div class="notif-empty__title">Community is temporarily unavailable.</div><div class="goal-empty-acts"><button type="button" class="btn btn-ghost btn--sm" onclick="loadCommunity(true)">Retry</button></div></li>`;
  } finally { commState.loading = false; }
}

async function commLoadMore() {
  if (commState.loading || !commState.more) return;
  const btn = document.getElementById('commLoadMoreBtn');
  commState.loading = true; if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
  try {
    const raw = await api(`/feed?limit=${COMM_PAGE}&offset=${commState.offset}`);
    const list = Array.isArray(raw) ? raw : [];
    const seen = new Set(commState.posts.map(p => p.ref));
    const fresh = list.map(normalizeCommunityPost).filter(p => p && !seen.has(p.ref));
    commState.posts.push(...fresh);
    commState.more = list.length >= COMM_PAGE;
    commState.offset += list.length;
    commState.open = {};                                   // collapse threads before the full re-render (no open-but-empty mismatch)
    renderCommunity();
    commAnnounce(fresh.length ? `${fresh.length} more ${fresh.length === 1 ? 'post' : 'posts'} loaded.` : (commState.more ? 'No new posts on this page.' : 'You’re all caught up.'));
  } catch (e) { commAnnounce('Could not load more posts.'); }
  finally { commState.loading = false; if (btn) { btn.disabled = false; btn.textContent = 'Load more posts'; } }
}

function commVisible() {
  const f = commState.filter;
  return commState.posts.filter(p => f === 'all' ? true : f === 'circles' ? p.scope === 'CIRCLE' : p.mine);
}

function renderCommunity() {
  const el = document.getElementById('feedList');
  if (!el) return;
  const items = commVisible();
  const lm = document.getElementById('commLoadMore');
  const showMore = !!commState.more;                       // page under ANY filter — GET /feed has no server filter, so
                                                           // filtered views must keep paging the raw feed and re-filtering
  if (!items.length) {
    let msg, cta;
    if (commState.filter !== 'all') {
      // Never assert absence we can't prove: more posts may be deeper in the feed.
      msg = showMore ? 'No matching posts loaded yet — load more to keep looking.' : 'No posts match this view.';
      cta = `<button type="button" class="btn btn-ghost btn--sm" onclick="commSetFilter('all')">Show all posts</button>`;
    } else {
      msg = showMore ? 'No posts loaded yet — load more to keep looking.' : 'No community posts yet.';
      cta = `<button type="button" class="btn btn-ghost btn--sm" onclick="commFocusComposer()">Write the first post</button>`;
    }
    el.innerHTML = `<li class="notif-empty"><div class="notif-empty__title">${msg}</div><div class="goal-empty-acts">${cta}</div></li>`;
    if (lm) lm.style.display = showMore ? 'flex' : 'none';  // keep paging reachable even on an empty view
    return;
  }
  el.innerHTML = items.map(commCard).join('');
  if (lm) lm.style.display = showMore ? 'flex' : 'none';
}

function commLikeLabel(ref) {
  const like = commState.likes[ref], liked = like && like.liked;
  if (like && typeof like.count === 'number') return liked ? `Appreciated · ${like.count}` : `Appreciate · ${like.count}`;
  return 'Appreciate';
}

function commCard(p) {
  const like = commState.likes[p.ref], liked = like && like.liked;
  const chip = p.scope === 'CIRCLE'
    ? '<span class="comm-chip comm-chip--circle">Circle</span>'
    : '<span class="comm-chip">Community</span>';
  const time = p.createdISO ? `<time datetime="${esc(p.createdISO)}">${esc(p.createdText)}</time>` : '';
  const open = commState.open[p.ref];
  const who = p.mine ? '<span class="comm-you">You</span>' : esc(p.authorLabel);
  return `<li class="comm-post"><article aria-label="Post by ${esc(p.authorLabel)}">
    <div class="comm-post__head">
      <span class="comm-post__who">${who}</span>
      <span class="comm-post__meta">${chip}${time}</span>
    </div>
    <div class="comm-post__body">${esc(p.body)}</div>
    <div class="comm-post__acts">
      <button type="button" class="comm-act${liked ? ' is-on' : ''}" id="comm-like-${esc(p.ref)}" onclick="commToggleLike('${esc(p.ref)}')" aria-pressed="${liked ? 'true' : 'false'}"><span aria-hidden="true">♥</span> ${esc(commLikeLabel(p.ref))}</button>
      <button type="button" class="comm-act" onclick="commToggleComments('${esc(p.ref)}',this)" aria-expanded="${open ? 'true' : 'false'}" aria-controls="comm-c-${esc(p.ref)}"><span aria-hidden="true">💬</span> Comments</button>
      <button type="button" class="comm-act" onclick="openReportDialog('POST','${esc(p.ref)}',this)"><span aria-hidden="true">⚑</span> Report</button>
    </div>
    <div class="comm-comments" id="comm-c-${esc(p.ref)}" style="display:${open ? 'block' : 'none'}"></div>
  </article></li>`;
}

// Appreciate (single generic like) — backend-authoritative. The feed payload
// carries no like state, so the count is shown ONLY from the like/unlike response
// (never optimistically inflated); before any interaction the count is unknown.
async function commToggleLike(id) {
  if (!_isUuid(id) || _commLikeBusy[id]) return;
  _commLikeBusy[id] = true;
  const btn = document.getElementById('comm-like-' + id);
  const wasLiked = commState.likes[id] && commState.likes[id].liked;
  if (btn) btn.disabled = true;
  try {
    const r = wasLiked
      ? await api(`/feed/${id}/like`, { method: 'DELETE' })
      : await api(`/feed/${id}/like`, { method: 'POST' });
    commState.likes[id] = { liked: !!r.liked, count: typeof r.like_count === 'number' ? r.like_count : (commState.likes[id] ? commState.likes[id].count : 0) };
    commRenderLikeBtn(id);
    commAnnounce(commState.likes[id].liked ? `Appreciated. ${commState.likes[id].count} in total.` : 'Appreciation removed.');
  } catch (e) {
    commAnnounce(safeError(e));
    if (btn) btn.disabled = false;
  } finally { _commLikeBusy[id] = false; }
}
function commRenderLikeBtn(id) {
  const btn = document.getElementById('comm-like-' + id);
  if (!btn) return;
  const liked = commState.likes[id] && commState.likes[id].liked;
  btn.classList.toggle('is-on', !!liked);
  btn.setAttribute('aria-pressed', liked ? 'true' : 'false');
  btn.innerHTML = `<span aria-hidden="true">♥</span> ${esc(commLikeLabel(id))}`;
  btn.disabled = false;
}

async function commToggleComments(id, trigger) {
  if (!_isUuid(id)) return;
  const box = document.getElementById('comm-c-' + id);
  if (!box) return;
  if (commState.open[id]) {
    commState.open[id] = false; box.style.display = 'none'; box.innerHTML = '';
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    return;
  }
  commState.open[id] = true; box.style.display = 'block';
  if (trigger) trigger.setAttribute('aria-expanded', 'true');
  box.innerHTML = '<span class="sk sk-line" style="width:55%"></span>';
  await commLoadComments(id);
}

async function commLoadComments(id) {
  const box = document.getElementById('comm-c-' + id);
  if (!box) return;
  try {
    const raw = await api(`/feed/${id}/comments`);
    if (!commState.open[id]) return;                       // thread was collapsed while the fetch was in flight — don't populate/announce a hidden box
    const list = (Array.isArray(raw) ? raw : []).map(normalizeComment).filter(Boolean);
    box.innerHTML = commCommentsHtml(id, list);
    commAnnounce(`${list.length} ${list.length === 1 ? 'comment' : 'comments'}.`);
  } catch (e) {
    if (!commState.open[id]) return;
    box.innerHTML = `<p class="comm-comments__empty">Comments are unavailable right now.</p>`;
  }
}

function commCommentsHtml(postId, list) {
  const rows = list.length
    ? `<ul class="comm-comments__list">${list.map(c => `
        <li class="comm-comment">
          <span class="comm-comment__who">${c.mine ? '<span class="comm-you">You</span>' : esc(c.authorLabel)}</span>${c.createdISO ? `<time class="comm-comment__meta" datetime="${esc(c.createdISO)}">${esc(c.createdText)}</time>` : ''}
          <div class="comm-comment__body">${esc(c.body)}</div>
          <button type="button" class="comm-comment__report" onclick="openReportDialog('COMMENT','${esc(c.ref)}',this)">Report</button>
        </li>`).join('')}</ul>`
    : `<p class="comm-comments__empty">No comments yet — be the first to reply.</p>`;
  return `${rows}
    <div class="comm-cbox">
      <label class="sr-only" for="comm-cbox-${esc(postId)}">Write a comment</label>
      <textarea id="comm-cbox-${esc(postId)}" rows="2" maxlength="4000" placeholder="Write a comment…"></textarea>
      <p class="err" id="comm-cerr-${esc(postId)}" role="alert" style="display:none"></p>
      <div class="comm-cbox__foot">
        <span class="comm-note">Comments are visible to other members. No account or payment details.</span>
        <button type="button" class="btn btn-primary btn--sm" onclick="postComment('${esc(postId)}',this)">Comment</button>
      </div>
    </div>`;
}

// Backend-authoritative comment — no optimistic insert; re-fetch after success.
async function postComment(postId, btn) {
  if (!_isUuid(postId) || _commCommentBusy[postId]) return;
  const ta = document.getElementById('comm-cbox-' + postId), err = document.getElementById('comm-cerr-' + postId);
  if (!ta) return;
  const body = ta.value.trim();
  if (err) err.style.display = 'none';
  if (!body) { if (err) { err.textContent = 'Write a comment first.'; err.style.display = 'block'; } ta.focus(); return; }
  if (body.length > 4000) { if (err) { err.textContent = 'Comments are limited to 4000 characters.'; err.style.display = 'block'; } return; }
  _commCommentBusy[postId] = true;
  if (btn) { btn.disabled = true; btn.textContent = 'Posting…'; }
  try {
    await api(`/feed/${postId}/comments`, { method: 'POST', body: JSON.stringify({ body }) });
    await commLoadComments(postId);                   // re-fetch; textarea is replaced (draft cleared only on success)
    commAnnounce('Comment posted.');
  } catch (e) {
    if (err) { err.textContent = safeError(e); err.style.display = 'block'; }   // draft preserved on failure
    _commCommentBusy[postId] = false;
    if (btn) { btn.disabled = false; btn.textContent = 'Comment'; }
    return;
  }
  _commCommentBusy[postId] = false;
}

function commCount() {
  const ta = document.getElementById('feedBody'), c = document.getElementById('feedCount');
  if (!ta || !c) return;
  const n = ta.value.length;
  c.textContent = `${n} / 4000`;
  c.classList.toggle('is-over', n >= 4000);
}

function commFocusComposer() {
  const ta = document.getElementById('feedBody');
  if (!ta) return;
  try { ta.scrollIntoView({ block: 'center', behavior: _commReduce() ? 'auto' : 'smooth' }); } catch (_) {}
  ta.focus();
}

// Backend-authoritative post — group_id omitted → GLOBAL post. No optimistic
// render; the feed is re-fetched and the newest post takes focus.
async function postFeed() {
  if (_commPostBusy) return;
  const btn = document.getElementById('feedBtn'), err = document.getElementById('feedErr'), ta = document.getElementById('feedBody');
  if (!ta) return;
  const body = ta.value.trim();
  if (err) err.style.display = 'none';
  if (!body) { if (err) { err.textContent = 'Write something to share first.'; err.style.display = 'block'; } ta.focus(); return; }
  if (body.length > 4000) { if (err) { err.textContent = 'Posts are limited to 4000 characters.'; err.style.display = 'block'; } return; }
  _commPostBusy = true;
  if (btn) { btn.disabled = true; btn.textContent = 'Posting…'; }
  try {
    await api('/feed', { method: 'POST', body: JSON.stringify({ body }) });
    ta.value = ''; commCount();                        // clear draft only after confirmed success
    commState.filter = 'all'; commSyncFilterButtons();
    await loadCommunity();
    commAnnounce('Your post was shared with the community.');
    const first = document.querySelector('#feedList .comm-post');
    if (first) { first.setAttribute('tabindex', '-1'); first.focus(); }
  } catch (e) {
    if (err) { err.textContent = safeError(e); err.style.display = 'block'; }   // draft preserved (ta not cleared)
  } finally { _commPostBusy = false; btn.disabled = false; btn.textContent = 'Post'; }
}

function commSetFilter(f) {
  if (!['all', 'circles', 'mine'].includes(f)) f = 'all';
  commState.filter = f; commState.open = {};           // close expanded comments on filter switch
  commSyncFilterButtons();
  renderCommunity();
  const labels = { all: 'Latest', circles: 'My circles', mine: 'My posts' };
  commAnnounce(`Showing ${labels[f]}.`);
}
function commSyncFilterButtons() {
  ['all', 'circles', 'mine'].forEach(f => { const b = document.getElementById('commF-' + f); if (b) b.setAttribute('aria-pressed', commState.filter === f ? 'true' : 'false'); });
}

// ── Report dialog (accessible; focus-trapped; Escape-to-close) ────────────────
let _commReportTarget = null, _commReportTrigger = null, _commReportBusy = false;
function openReportDialog(type, id, trigger) {
  if (!['POST', 'COMMENT'].includes(type) || !_isUuid(id)) return;
  _commReportTarget = { type, id }; _commReportTrigger = trigger || document.activeElement;
  const dlg = document.getElementById('commReportDialog');
  const err = document.getElementById('commReportErr'); if (err) err.style.display = 'none';
  const detail = document.getElementById('commReportDetail'); if (detail) detail.value = '';
  const first = document.querySelector('#commReportForm input[name="commReason"]'); if (first) first.checked = true;
  const submit = document.getElementById('commReportSubmit'); if (submit) { submit.disabled = false; submit.textContent = 'Submit report'; }
  dlg.dataset.busy = '0'; dlg.classList.add('is-open');
  document.addEventListener('keydown', _commReportTrapKey, true);
  setTimeout(() => { if (first) first.focus(); }, 0);
}
function closeReportDialog() {
  const dlg = document.getElementById('commReportDialog'); if (dlg) dlg.classList.remove('is-open');
  document.removeEventListener('keydown', _commReportTrapKey, true);
  const t = _commReportTrigger; _commReportTarget = null; _commReportTrigger = null;
  if (t && typeof t.focus === 'function') { try { t.focus(); } catch (e) {} }
}
function _commReportTrapKey(e) {
  const d = document.getElementById('commReportDialog'); if (!d) return;
  if (e.key === 'Escape') { e.preventDefault(); if (d.dataset.busy === '1') return; closeReportDialog(); return; }
  if (e.key === 'Tab') {
    const els = [...d.querySelectorAll('input,select,button,textarea,a[href]')].filter(x => !x.disabled && x.offsetParent !== null);
    // Collapse each radio group to a SINGLE tab stop (its checked member, else the
    // first) so first/last match native tab order and Shift+Tab can't slip past it.
    const handled = new Set(); const f = [];
    for (const x of els) {
      if (x.type === 'radio' && x.name) {
        if (handled.has(x.name)) continue;
        handled.add(x.name);
        const group = els.filter(y => y.type === 'radio' && y.name === x.name);
        f.push(group.find(y => y.checked) || group[0]);
      } else { f.push(x); }
    }
    if (!f.length) { e.preventDefault(); return; }
    const first = f[0], last = f[f.length - 1];
    const active = document.activeElement;
    if (!d.contains(active)) { e.preventDefault(); first.focus(); return; }
    let cur = active;
    if (active.type === 'radio' && active.name) cur = f.find(el => el.type === 'radio' && el.name === active.name) || active;
    if (e.shiftKey && cur === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && cur === last) { e.preventDefault(); first.focus(); }
  }
}
async function submitReport() {
  if (_commReportBusy || !_commReportTarget) return;
  const { type, id } = _commReportTarget;
  if (!_isUuid(id)) { closeReportDialog(); return; }
  const dlg = document.getElementById('commReportDialog'); dlg.dataset.busy = '1';
  const err = document.getElementById('commReportErr'); if (err) err.style.display = 'none';
  const submit = document.getElementById('commReportSubmit');
  const sel = document.querySelector('#commReportForm input[name="commReason"]:checked');
  const detail = (document.getElementById('commReportDetail') || {}).value || '';
  let reason = sel ? sel.value : 'Something else';
  if (detail.trim()) reason += ` — ${detail.trim()}`;
  reason = reason.slice(0, 1000);                      // backend max 1000
  _commReportBusy = true;
  if (submit) { submit.disabled = true; submit.textContent = 'Submitting…'; }
  try {
    await api('/community/report', { method: 'POST', body: JSON.stringify({ target_type: type, target_id: id, reason }) });   // no optimistic removal — content stays visible
    dlg.dataset.busy = '0'; _commReportBusy = false;
    closeReportDialog();
    commAnnounce('Thanks — your report was submitted for review.');
  } catch (e) {
    dlg.dataset.busy = '0'; _commReportBusy = false;
    if (err) { err.textContent = safeError(e); err.style.display = 'block'; }
    if (submit) { submit.disabled = false; submit.textContent = 'Submit report'; }
  }
}
