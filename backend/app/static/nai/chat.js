// Vanilla JS chat client.
//   - Tools off  → SSE stream via EventSource (faster, no tools)
//   - Tools on   → POST /nai/chat (full tool loop, no streaming)
//
// JWT auth: header for POST, query param for SSE (EventSource can't set headers).
// JWT in URL is acceptable while the server is 127.0.0.1-only. Phase B must
// move to HttpOnly cookies before any public exposure.

const TOKEN_KEY = "nai_jwt";

const els = {
  messages: document.getElementById("messages"),
  input:    document.getElementById("input"),
  form:     document.getElementById("composer"),
  send:     document.getElementById("send"),
  useTools: document.getElementById("use-tools"),
  local:    document.getElementById("prefer-local"),
  newConv:  document.getElementById("new-conv"),
  status:   document.getElementById("status"),
};

let conversationId = null;
let token = localStorage.getItem(TOKEN_KEY);

function ensureToken() {
  if (token) return token;
  const t = window.prompt("Paste your JWT (from /auth/login):");
  if (!t) return null;
  localStorage.setItem(TOKEN_KEY, t);
  token = t;
  return t;
}

function appendMessage(role, content) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = content;
  els.messages.appendChild(div);
  els.messages.scrollTop = els.messages.scrollHeight;
  return div;
}

function setStatus(text) {
  els.status.textContent = text || "";
}

async function sendWithTools(message) {
  setStatus("Thinking… (tools enabled)");
  const resp = await fetch("/nai/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      use_tools: true,
      prefer_local: els.local.checked,
    }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    appendMessage("assistant", `Error ${resp.status}: ${text}`);
    setStatus("");
    return;
  }
  const data = await resp.json();
  conversationId = data.conversation_id;
  appendMessage("assistant", data.message.content);
  setStatus(
    `adapter=${data.message.adapter || "?"} cost=$${data.total_cost_usd.toFixed(4)}`
  );
}

function sendStreaming(message) {
  setStatus("Streaming…");
  const params = new URLSearchParams({
    message,
    prefer_local: els.local.checked ? "true" : "false",
    token,
  });
  if (conversationId) params.set("conversation_id", conversationId);

  const url = `/nai/chat/stream?${params.toString()}`;
  const evtSource = new EventSource(url);
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
      setStatus("Done");
    } else if (data.type === "error") {
      bubble.textContent += `\n[error: ${data.error}]`;
      evtSource.close();
      setStatus("");
    }
  };

  evtSource.onerror = () => {
    evtSource.close();
    setStatus("Stream error");
  };
}

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!ensureToken()) return;
  const message = els.input.value.trim();
  if (!message) return;

  appendMessage("user", message);
  els.input.value = "";
  els.send.disabled = true;

  try {
    if (els.useTools.checked) {
      await sendWithTools(message);
    } else {
      sendStreaming(message);
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
