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
  els.messages.appendChild(div);
  els.messages.scrollTop = els.messages.scrollHeight;
  return div;
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

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
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

if (els.logout) {
  els.logout.addEventListener("click", () => window.logout());
}

// On page load, confirm we're authenticated. If not, redirect to login.
window.requireAuthOrRedirect("/kai-ui/login.html");
