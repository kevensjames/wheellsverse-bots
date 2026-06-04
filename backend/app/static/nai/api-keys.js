// Self-service API key management — list, create, revoke.
// Requires auth (cookie). Paid tier check happens server-side.

(function () {
  const els = {
    list: document.getElementById("key-list"),
    newBtn: document.getElementById("new-key-btn"),
    error: document.getElementById("error"),
    newlyCreated: document.getElementById("newly-created"),
    newKeyPlaintext: document.getElementById("new-key-plaintext"),
    copyBtn: document.getElementById("copy-key-btn"),
    logout: document.getElementById("logout-btn"),
  };

  function clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function showError(msg) {
    els.error.textContent = msg;
    els.error.classList.add("shown");
    setTimeout(() => els.error.classList.remove("shown"), 8000);
  }

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString();
  }

  function renderMutedLi(text, link) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = text;
    if (link) {
      const a = document.createElement("a");
      a.href = link.href;
      a.textContent = link.text;
      li.appendChild(a);
    }
    return li;
  }

  async function loadKeys() {
    try {
      const r = await fetch("/account/api-keys", { credentials: "same-origin" });
      if (r.status === 401) {
        window.location.href = "/kai-ui/login.html?next=" + encodeURIComponent("/kai-ui/api-keys.html");
        return;
      }
      if (r.status === 402) {
        clearChildren(els.list);
        els.list.appendChild(
          renderMutedLi("API keys are a paid feature. ",
                        { href: "/kai-ui/pricing.html", text: "Upgrade →" })
        );
        els.newBtn.disabled = true;
        return;
      }
      if (!r.ok) {
        showError("Failed to load keys: HTTP " + r.status);
        return;
      }
      const items = await r.json();
      renderKeys(items);
    } catch (e) {
      showError("Network error loading keys");
    }
  }

  function renderKeys(items) {
    clearChildren(els.list);
    if (!items.length) {
      els.list.appendChild(
        renderMutedLi("No keys yet. Click + New key to issue one.")
      );
      return;
    }
    for (const k of items) {
      const li = document.createElement("li");
      const meta = document.createElement("div");
      meta.className = "meta";

      const prefix = document.createElement("span");
      prefix.className = "prefix";
      prefix.textContent = k.prefix + "...";

      const label = document.createElement("span");
      label.className = "label";
      label.textContent = k.label || "(no label)";

      const stamp = document.createElement("div");
      stamp.className = "stamp";
      stamp.textContent =
        "Created " + fmtDate(k.created_at) +
        (k.last_used_at ? " · Last used " + fmtDate(k.last_used_at) : " · Never used");

      meta.appendChild(prefix);
      meta.appendChild(label);
      meta.appendChild(stamp);

      const btn = document.createElement("button");
      btn.className = "revoke-btn";
      btn.type = "button";
      btn.textContent = "Revoke";
      btn.addEventListener("click", () => revoke(k.id));

      li.appendChild(meta);
      li.appendChild(btn);
      els.list.appendChild(li);
    }
  }

  async function createKey() {
    const label = prompt("Optional label (e.g. 'my laptop', 'github actions'):", "");
    if (label === null) return;  // user canceled
    els.newBtn.disabled = true;
    try {
      const r = await fetch("/account/api-keys", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: label || null }),
      });
      if (r.status === 402) {
        showError("API keys require a paid plan. Upgrade at /kai-ui/pricing.html");
        return;
      }
      if (!r.ok) {
        showError("Failed to create key: HTTP " + r.status);
        return;
      }
      const data = await r.json();
      els.newKeyPlaintext.textContent = data.key;
      els.newlyCreated.hidden = false;
      els.newlyCreated.scrollIntoView({ behavior: "smooth" });
      loadKeys();
    } catch (e) {
      showError("Network error creating key");
    } finally {
      els.newBtn.disabled = false;
    }
  }

  async function revoke(keyId) {
    if (!confirm("Revoke this key? Any apps using it will start failing immediately.")) return;
    try {
      const r = await fetch("/account/api-keys/" + keyId, {
        method: "DELETE",
        credentials: "same-origin",
      });
      if (r.status === 204) {
        loadKeys();
        return;
      }
      showError("Failed to revoke: HTTP " + r.status);
    } catch (e) {
      showError("Network error revoking key");
    }
  }

  if (els.newBtn) els.newBtn.addEventListener("click", createKey);
  if (els.copyBtn) {
    els.copyBtn.addEventListener("click", () => {
      const text = els.newKeyPlaintext.textContent;
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text);
        els.copyBtn.textContent = "Copied ✓";
        setTimeout(() => (els.copyBtn.textContent = "Copy"), 2000);
      }
    });
  }
  if (els.logout) els.logout.addEventListener("click", () => window.logout && window.logout());

  window.requireAuthOrRedirect("/kai-ui/login.html");
  loadKeys();
})();
