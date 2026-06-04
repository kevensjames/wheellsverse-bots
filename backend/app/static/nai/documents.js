// Documents library — upload PDF/TXT/MD, list, delete.

(function () {
  const els = {
    list: document.getElementById("doc-list"),
    uploadBtn: document.getElementById("upload-btn"),
    fileInput: document.getElementById("file-input"),
    error: document.getElementById("error"),
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
    return new Date(iso).toLocaleString();
  }

  function fmtKb(chars) {
    if (chars < 1000) return chars + " chars";
    return Math.round(chars / 1000) + "k chars";
  }

  function renderMuted(text, link) {
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

  async function loadDocs() {
    try {
      const r = await fetch("/account/documents", { credentials: "same-origin" });
      if (r.status === 401) {
        window.location.href = "/kai-ui/login.html?next=" + encodeURIComponent("/kai-ui/documents.html");
        return;
      }
      if (r.status === 402) {
        clearChildren(els.list);
        els.list.appendChild(renderMuted(
          "Documents are a paid feature. ",
          { href: "/kai-ui/pricing.html", text: "Upgrade →" },
        ));
        els.uploadBtn.disabled = true;
        return;
      }
      if (!r.ok) {
        showError("Failed to load library: HTTP " + r.status);
        return;
      }
      const items = await r.json();
      renderDocs(items);
    } catch (e) {
      showError("Network error loading library");
    }
  }

  function renderDocs(items) {
    clearChildren(els.list);
    if (!items.length) {
      els.list.appendChild(renderMuted("No documents yet. Click Upload to add one."));
      return;
    }
    for (const d of items) {
      const li = document.createElement("li");
      const meta = document.createElement("div");
      meta.className = "meta";

      const name = document.createElement("span");
      name.className = "filename";
      name.textContent = d.filename;

      const stamp = document.createElement("div");
      stamp.className = "stamp";
      stamp.textContent = fmtKb(d.text_len) + " · " + fmtDate(d.created_at);

      meta.appendChild(name);
      meta.appendChild(stamp);

      const btn = document.createElement("button");
      btn.className = "delete-btn";
      btn.type = "button";
      btn.textContent = "Delete";
      btn.addEventListener("click", () => deleteDoc(d.id, d.filename));

      li.appendChild(meta);
      li.appendChild(btn);
      els.list.appendChild(li);
    }
  }

  async function uploadFile(file) {
    const fd = new FormData();
    fd.append("file", file);
    els.uploadBtn.disabled = true;
    els.uploadBtn.textContent = "Uploading…";
    try {
      const r = await fetch("/account/documents", {
        method: "POST",
        credentials: "same-origin",
        body: fd,
      });
      if (r.status === 402) {
        showError("Documents require a paid plan. /kai-ui/pricing.html");
        return;
      }
      if (!r.ok) {
        let msg = "Upload failed: HTTP " + r.status;
        try {
          const data = await r.json();
          if (data && data.detail) msg += " — " + data.detail;
        } catch {}
        showError(msg);
        return;
      }
      loadDocs();
    } catch (e) {
      showError("Network error during upload");
    } finally {
      els.uploadBtn.disabled = false;
      els.uploadBtn.textContent = "+ Upload a document";
      els.fileInput.value = "";  // reset so same file can be re-picked
    }
  }

  async function deleteDoc(docId, filename) {
    if (!confirm("Delete \"" + filename + "\"? This can't be undone.")) return;
    try {
      const r = await fetch("/account/documents/" + docId, {
        method: "DELETE",
        credentials: "same-origin",
      });
      if (r.status === 204) {
        loadDocs();
        return;
      }
      showError("Delete failed: HTTP " + r.status);
    } catch (e) {
      showError("Network error during delete");
    }
  }

  if (els.uploadBtn) els.uploadBtn.addEventListener("click", () => els.fileInput.click());
  if (els.fileInput) els.fileInput.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) uploadFile(file);
  });
  if (els.logout) els.logout.addEventListener("click", () => window.logout && window.logout());

  window.requireAuthOrRedirect("/kai-ui/login.html");
  loadDocs();
})();
