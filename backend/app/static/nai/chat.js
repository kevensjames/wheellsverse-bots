// Vanilla JS chat client. Stage 6: cookie auth.
//   - Tools off  → SSE stream via EventSource (cookies auto-sent same-origin)
//   - Tools on   → POST /kai/chat (cookies auto-sent same-origin)
//
// No JWT touches JS anymore. The server issues HttpOnly cookies on
// /auth/login + /auth/signup; we never read them, only send them implicitly.

const els = {
  messages: document.getElementById("messages"),
  input:    document.getElementById("input"),
  form:     document.getElementById("composer"),
  send:     document.getElementById("send"),
  useTools: document.getElementById("use-tools"),
  local:    document.getElementById("prefer-local"),
  newConv:  document.getElementById("new-conv"),
  status:   document.getElementById("status"),
  logout:   document.getElementById("logout-btn"),
};

let conversationId = null;

function appendMessage(role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = content;
  if (role === "assistant") {
    attachSpeakButton(div);
  }
  els.messages.appendChild(div);
  els.messages.scrollTop = els.messages.scrollHeight;
  return div;
}

// Turn inline citation markers an agent emits — [PMID 12345678] and
// [source: filename #pos] / [From "filename" #pos] — into clickable chips
// below the message, so the professional layer's sourcing is visible at a
// glance instead of buried in the text. Idempotent: removes a prior chip row
// before re-rendering (streaming calls it once at the end).
function renderCitations(messageDiv, text) {
  if (!messageDiv) return;
  const old = messageDiv.querySelector(":scope > .citation-chips");
  if (old) old.remove();
  const cites = [];
  const seen = new Set();
  const add = (label, href) => {
    const key = label.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    cites.push({ label, href });
  };
  let m;
  const pmid = /\[\s*PMID:?\s*(\d+)\s*\]/gi;
  while ((m = pmid.exec(text))) add(`PMID ${m[1]}`, `https://pubmed.ncbi.nlm.nih.gov/${m[1]}/`);
  const src = /\[\s*(?:source:\s*|From\s*")\s*([^\]"#]+?)["']?\s*(?:,?\s*(?:chunk\s*)?#\s*(\d+))?\s*\]/gi;
  while ((m = src.exec(text))) {
    const name = (m[1] || "").trim();
    if (name) add(m[2] ? `${name} #${m[2]}` : name, null);
  }
  if (!cites.length) return;
  const row = document.createElement("div");
  row.className = "citation-chips";
  const lbl = document.createElement("span");
  lbl.className = "citation-chips-label";
  lbl.textContent = "Sources:";
  row.appendChild(lbl);
  const g = document.createElement("span");
  g.className = "cite-chip grounded-chip";
  g.textContent = `✓ ${cites.length} source${cites.length > 1 ? "s" : ""}`;
  row.appendChild(g);
  cites.forEach((c) => {
    const el = document.createElement(c.href ? "a" : "span");
    el.className = "cite-chip";
    el.textContent = c.label;
    if (c.href) { el.href = c.href; el.target = "_blank"; el.rel = "noopener"; }
    row.appendChild(el);
  });
  messageDiv.appendChild(row);
}

// Single audio element reused across all speak clicks. Stopping the
// current audio when a new one starts prevents two utterances overlapping.
let _ttsAudio = null;

function attachSpeakButton(messageDiv) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "speak-btn";
  btn.title = "Read aloud";
  btn.textContent = "🔊";
  btn.addEventListener("click", async () => {
    // Pull whatever text is in the bubble RIGHT NOW (not at create time —
    // streaming responses fill the bubble after creation, and the button
    // should read whatever the user can currently see).
    // Walk text only, excluding the button itself.
    const text = Array.from(messageDiv.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE || (n.nodeType === Node.ELEMENT_NODE && !n.classList?.contains("speak-btn") && !n.classList?.contains("citation-chips")))
      .map((n) => n.textContent)
      .join("")
      .trim();
    if (!text) return;
    btn.disabled = true;
    btn.textContent = "…";
    try {
      const resp = await fetch("/kai/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ text }),
      });
      if (resp.status === 402) {
        btn.textContent = "💎";
        btn.title = "Voice output requires a paid plan";
        return;
      }
      if (!resp.ok) {
        btn.textContent = "✗";
        btn.title = `TTS error ${resp.status}`;
        return;
      }
      const blob = await resp.blob();
      if (_ttsAudio) {
        _ttsAudio.pause();
        URL.revokeObjectURL(_ttsAudio.src);
      }
      _ttsAudio = new Audio(URL.createObjectURL(blob));
      _ttsAudio.onended = () => {
        btn.textContent = "🔊";
        btn.disabled = false;
      };
      await _ttsAudio.play();
    } catch (e) {
      btn.textContent = "✗";
      btn.title = `TTS error: ${e.message}`;
      btn.disabled = false;
    }
  });
  messageDiv.appendChild(btn);
}

function setStatus(text) {
  els.status.textContent = text || "";
}

async function sendWithTools(message) {
  setStatus("Thinking… (tools enabled)");
  const resp = await fetch("/kai/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      use_tools: true,
      prefer_local: els.local.checked,
    }),
  });
  if (resp.status === 401) {
    window.location.href = "/kai-ui/login.html";
    return;
  }
  if (!resp.ok) {
    const text = await resp.text();
    appendMessage("assistant", `Error ${resp.status}: ${text}`);
    setStatus("");
    return;
  }
  const data = await resp.json();
  conversationId = data.conversation_id;
  renderCitations(appendMessage("assistant", data.message.content), data.message.content);
  setStatus(
    `adapter=${data.message.adapter || "?"} cost=$${data.total_cost_usd.toFixed(4)}`
  );
}

function sendStreaming(message) {
  setStatus("Streaming…");
  const params = new URLSearchParams({
    message,
    prefer_local: els.local.checked ? "true" : "false",
  });
  if (conversationId) params.set("conversation_id", conversationId);

  // EventSource needs withCredentials=true to send cookies even on same-origin
  // for some browsers; setting it is safe everywhere.
  const url = `/kai/chat/stream?${params.toString()}`;
  const evtSource = new EventSource(url, { withCredentials: true });
  const bubble = appendMessage("assistant", "");

  evtSource.onmessage = (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch { return; }

    if (data.type === "meta") {
      conversationId = data.conversation_id;
    } else if (data.type === "delta") {
      bubble.textContent += data.content;
      els.messages.scrollTop = els.messages.scrollHeight;
    } else if (data.type === "done") {
      evtSource.close();
      renderCitations(bubble, bubble.textContent);
      setStatus("Done");
    } else if (data.type === "error") {
      bubble.textContent += `\n[error: ${data.error}]`;
      evtSource.close();
      setStatus("");
    }
  };

  evtSource.onerror = () => {
    evtSource.close();
    setStatus("Stream error — your session may have expired. Try logging in again.");
  };
}

// ── Document attachment ─────────────────────────────────────────────────
const _docTextCache = new Map();  // doc_id → full text

async function loadDocPicker() {
  const select = document.getElementById("doc-attach");
  if (!select) return;
  try {
    const r = await fetch("/account/documents", { credentials: "same-origin" });
    if (r.status === 402) {
      // Free tier — keep the picker disabled with a note
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(paid only)";
      select.firstChild.replaceWith(opt);
      select.disabled = true;
      return;
    }
    if (!r.ok) return;
    const items = await r.json();
    // Keep the "— none —" option, append docs
    for (const d of items) {
      const opt = document.createElement("option");
      opt.value = d.id;
      opt.textContent = d.filename;
      select.appendChild(opt);
    }
  } catch (e) { /* fail silently */ }
}
loadDocPicker();

async function retrieveDocContext(docId, userMessage) {
  // RAG v2: top-k chunks instead of full text. Cheap (~1 query embed)
  // and scales to docs of any size without blowing the model's context.
  const params = new URLSearchParams({ q: userMessage, k: "5" });
  const r = await fetch(
    "/account/documents/" + docId + "/retrieve?" + params.toString(),
    { credentials: "same-origin" },
  );
  if (!r.ok) return null;
  const data = await r.json();
  return data.context || null;  // server-rendered prelude string
}

async function maybeFetchDocText(docId) {
  // v1 fallback: full text. Kept for the case where retrieval returns
  // nothing (e.g. embeddings failed during upload).
  if (_docTextCache.has(docId)) return _docTextCache.get(docId);
  const r = await fetch("/account/documents/" + docId + "/text",
                       { credentials: "same-origin" });
  if (!r.ok) return null;
  const data = await r.json();
  _docTextCache.set(docId, data.text);
  return data.text;
}

async function composeWithDoc(userMessage) {
  const select = document.getElementById("doc-attach");
  const docId = select && select.value;
  if (!docId) return userMessage;
  // Try RAG v2 retrieval first
  const ctx = await retrieveDocContext(docId, userMessage);
  if (ctx) {
    return ctx + "\nQuestion:\n" + userMessage;
  }
  // Fallback to v1 full-text injection
  const text = await maybeFetchDocText(docId);
  if (!text) return userMessage;
  const opt = select.options[select.selectedIndex];
  const fname = opt ? opt.textContent : "document";
  return (
    "Reference document (\"" + fname + "\"):\n" +
    "---\n" + text + "\n---\n\n" +
    "Question:\n" + userMessage
  );
}

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = els.input.value.trim();
  if (!message) return;

  appendMessage("user", message);   // show ORIGINAL message in UI
  els.input.value = "";
  els.send.disabled = true;
  hideStarterPrompts();

  try {
    const composed = await composeWithDoc(message);
    if (els.useTools.checked) {
      await sendWithTools(composed);
    } else {
      sendStreaming(composed);
    }
  } finally {
    setTimeout(() => {
      els.send.disabled = false;
      els.input.focus();
    }, 200);
  }
});

els.newConv.addEventListener("click", () => {
  conversationId = null;
  els.messages.replaceChildren();
  setStatus("New conversation");
  els.input.focus();
});

// Enter to send, Shift+Enter for newline
els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    els.form.requestSubmit();
  }
});

if (els.logout) {
  els.logout.addEventListener("click", () => window.logout());
}

// On page load, confirm we're authenticated. If not, redirect to login.
window.requireAuthOrRedirect("/kai-ui/login.html");

// Fetch current plan and update the header badge. Cheap call; runs once per
// page load, again after the user returns from Stripe Checkout (?subscribed=1).
async function refreshPlanBadge() {
  const badge = document.getElementById("plan-badge");
  const pricingLink = document.getElementById("pricing-link");
  const banner = document.getElementById("payment-banner");
  if (!badge) return;
  try {
    const r = await fetch("/billing/subscription", { credentials: "same-origin" });
    if (!r.ok) return;
    const data = await r.json();
    const plan = (data.plan_code || "free").toUpperCase();
    const status = (data.status || "free").toLowerCase();
    badge.textContent = plan === "FREE" ? "FREE" : `${plan} ✓`;
    badge.className = "plan-badge plan-" + plan.toLowerCase();
    badge.hidden = false;
    // Hide "Pricing" link once subscribed — no reason to upsell paying users.
    if (pricingLink && plan !== "FREE") pricingLink.hidden = true;
    // Past-due banner: show if Stripe says payment failed.
    if (banner) banner.hidden = status !== "past_due";
  } catch (e) {
    // fail silently — badge stays hidden
  }
}

async function openBillingPortal() {
  const btn = document.getElementById("payment-banner-fix");
  if (btn) btn.disabled = true;
  try {
    const r = await fetch("/billing/portal", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    });
    if (!r.ok) {
      alert("Couldn't open Stripe portal (HTTP " + r.status + "). Try again.");
      return;
    }
    const data = await r.json();
    if (data.portal_url) window.location.href = data.portal_url;
  } catch (e) {
    alert("Network error opening Stripe portal");
  } finally {
    if (btn) btn.disabled = false;
  }
}

const _bannerBtn = document.getElementById("payment-banner-fix");
if (_bannerBtn) _bannerBtn.addEventListener("click", openBillingPortal);

refreshPlanBadge();

// ── Starter prompts ─────────────────────────────────────────────────────
// Shown on first load. Clicking a chip fills the composer + focuses it.
// Hides itself after the first message is sent so returning users don't
// see them every time.
function wireStarterPrompts() {
  const wrap = document.getElementById("starter-prompts");
  if (!wrap) return;
  const chips = wrap.querySelectorAll(".starter-chip");
  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      const prompt = chip.getAttribute("data-prompt") || "";
      els.input.value = prompt;
      els.input.focus();
      const m = prompt.match(/\[[^\]]+\]/);
      if (m) {
        const start = prompt.indexOf(m[0]);
        els.input.setSelectionRange(start, start + m[0].length);
      }
    });
  });
}
wireStarterPrompts();

// ── Voice input (MediaRecorder → /kai/transcribe) ───────────────────────
// Click mic → start recording, click again → stop + upload + fill input.
// Requires HTTPS (we have it) + microphone permission (browser prompts once).
(function wireMic() {
  const btn = document.getElementById("mic-btn");
  if (!btn) return;
  let recorder = null;
  let chunks = [];
  let active = false;

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = new MediaRecorder(stream);
      chunks = [];
      recorder.addEventListener("dataavailable", (e) => {
        if (e.data && e.data.size > 0) chunks.push(e.data);
      });
      recorder.addEventListener("stop", async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (!chunks.length) return;
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        await uploadAndFill(blob);
      });
      recorder.start();
      active = true;
      btn.classList.add("mic-recording");
      btn.textContent = "⏺";
      setStatus("Recording… click mic again to stop");
    } catch (e) {
      alert("Microphone access denied or unavailable.");
    }
  }

  function stop() {
    if (recorder && recorder.state !== "inactive") recorder.stop();
    active = false;
    btn.classList.remove("mic-recording");
    btn.textContent = "🎤";
    setStatus("Transcribing…");
  }

  async function uploadAndFill(blob) {
    const fd = new FormData();
    fd.append("file", blob, "voice.webm");
    try {
      const r = await fetch("/kai/transcribe", {
        method: "POST",
        credentials: "same-origin",
        body: fd,
      });
      if (r.status === 402) {
        alert("Voice input is a paid feature. Upgrade at /kai-ui/pricing.html");
        setStatus("");
        return;
      }
      if (!r.ok) {
        setStatus("Transcription failed (HTTP " + r.status + ")");
        return;
      }
      const data = await r.json();
      const text = (data.text || "").trim();
      if (!text) { setStatus("No speech detected."); return; }
      // Append to existing input rather than overwrite — user might be mid-thought
      els.input.value = (els.input.value.trim() ? els.input.value.trim() + " " : "") + text;
      els.input.focus();
      setStatus("");
    } catch (e) {
      setStatus("Network error during transcription");
    }
  }

  btn.addEventListener("click", () => (active ? stop() : start()));
})();

function hideStarterPrompts() {
  const wrap = document.getElementById("starter-prompts");
  if (wrap) wrap.hidden = true;
}

// ── Cancel survey ────────────────────────────────────────────────────────
// Fires when the user comes back from Stripe portal after canceling. Stripe
// returns them to BILLING_PUBLIC_UPGRADE_URL, but the chat link includes
// ?canceled=1 in some paths — we honor either.
async function submitCancelReason(reasonCode, freeText) {
  try {
    await fetch("/billing/cancellation-reason", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason_code: reasonCode, free_text: freeText || null }),
    });
  } catch (e) { /* fail silently — survey is nice-to-have */ }
}

function hideCancelModal() {
  const modal = document.getElementById("cancel-modal");
  if (modal) modal.hidden = true;
  if (history.replaceState) {
    const u = new URL(window.location.href);
    u.searchParams.delete("canceled");
    history.replaceState({}, "", u.toString());
  }
}

async function applyWinback() {
  const btn = document.getElementById("winback-accept");
  if (btn) { btn.disabled = true; btn.textContent = "Applying…"; }
  try {
    const r = await fetch("/billing/winback/apply-discount", {
      method: "POST",
      credentials: "same-origin",
    });
    if (!r.ok) {
      alert("Couldn't apply discount (HTTP " + r.status + "). The cancellation can still proceed.");
      return false;
    }
    const data = await r.json();
    alert(data.message || "Discount applied. You're staying on Pro at 50% off next month.");
    return true;
  } catch (e) {
    alert("Network error applying discount.");
    return false;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Yes — apply 50% off"; }
  }
}

async function wireCancelSurvey() {
  const modal = document.getElementById("cancel-modal");
  if (!modal) return;

  // Gate 1: URL must have ?canceled=1 EXACTLY — proper param parsing, not
  // a substring match (the old `.includes("canceled=1")` would match any
  // URL containing that string anywhere, e.g. ?next=/canceled=1/foo).
  const params = new URLSearchParams(window.location.search);
  if (params.get("canceled") !== "1") return;

  // Gate 2: user must have HAD a subscription. A fresh signup with no
  // billing history should never see a cancel survey — that's the bug
  // we just fixed where signups were landing on the feedback modal.
  // Check /billing/subscription: status must be canceled / past_due /
  // active (anything except 'free').
  try {
    const r = await fetch("/billing/subscription", { credentials: "same-origin" });
    if (!r.ok) return;
    const data = await r.json();
    const status = (data.status || "free").toLowerCase();
    if (status === "free") return;
  } catch (e) {
    return;  // fail closed — don't show the modal if we can't verify
  }

  modal.hidden = false;
  const skipBtn = document.getElementById("cancel-modal-skip");
  const form = document.getElementById("cancel-form");
  const offer = document.getElementById("winback-offer");
  const acceptBtn = document.getElementById("winback-accept");
  const declineBtn = document.getElementById("winback-decline");

  if (skipBtn) skipBtn.addEventListener("click", hideCancelModal);

  if (form) form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const selected = form.querySelector('input[name="reason"]:checked');
    if (!selected) { alert("Pick one option, or click Skip."); return; }
    const free = document.getElementById("cancel-free-text").value.trim();
    await submitCancelReason(selected.value, free);

    // If the reason is "too_expensive", reveal the winback offer and DON'T
    // close the modal yet. Other reasons → just close (the offer wouldn't
    // change their mind).
    if (selected.value === "too_expensive" && offer) {
      form.hidden = true;
      offer.hidden = false;
    } else {
      hideCancelModal();
    }
  });

  if (acceptBtn) acceptBtn.addEventListener("click", async () => {
    const ok = await applyWinback();
    hideCancelModal();
    if (ok) refreshPlanBadge();   // status may have flipped past_due → active
  });
  if (declineBtn) declineBtn.addEventListener("click", hideCancelModal);
}
wireCancelSurvey();

// If we just returned from Stripe Checkout, poll briefly until the webhook
// catches up. Stripe events usually land in <2s but can take up to ~10s
// under load. Polling avoids a hard reload + lets the badge flip live.
if (window.location.search.includes("subscribed=1")) {
  let tries = 0;
  const poll = setInterval(async () => {
    tries += 1;
    await refreshPlanBadge();
    const badge = document.getElementById("plan-badge");
    if (badge && !badge.hidden && !badge.textContent.startsWith("FREE")) {
      clearInterval(poll);
    } else if (tries >= 10) {
      clearInterval(poll);
    }
  }, 1500);
}
