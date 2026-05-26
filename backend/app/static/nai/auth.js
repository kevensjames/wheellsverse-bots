// Shared auth helpers for signup.html, login.html, pricing.html.
//
// Cookies (HttpOnly nai_access + nai_refresh) are set by the server on
// successful /auth/signup and /auth/login. The browser sends them automatically
// on subsequent same-origin requests — so JavaScript never touches the JWT.
//
// We rely on the response body's TokenResponse only to confirm success; we do
// NOT store the access_token client-side (that would defeat the HttpOnly cookie).

function showError(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.classList.add("visible");
}

function clearError(el) {
  if (!el) return;
  el.textContent = "";
  el.classList.remove("visible");
}

async function bindAuthForm({
  formId, submitId, errorId, endpoint, buildBody, successRedirect,
}) {
  const form   = document.getElementById(formId);
  const button = document.getElementById(submitId);
  const error  = document.getElementById(errorId);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearError(error);
    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = "Working…";

    try {
      const body = buildBody();
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });

      if (!resp.ok) {
        let detail = `${resp.status} ${resp.statusText}`;
        try {
          const data = await resp.json();
          if (data && data.detail) detail = data.detail;
        } catch (_) { /* non-JSON body */ }
        showError(error, detail);
        return;
      }

      // Cookies are now set by the server. Forward to the chat page (or wherever
      // the caller wanted).
      window.location.href = successRedirect;
    } catch (err) {
      showError(error, `Network error: ${err.message || err}`);
    } finally {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  });
}

// Optional helper for pages that should redirect to login when not authed.
async function requireAuthOrRedirect(loginUrl = "/nai-ui/login.html") {
  try {
    const resp = await fetch("/auth/me", { credentials: "include" });
    if (resp.ok) {
      return await resp.json();
    }
  } catch (_) { /* fall through */ }
  const next = encodeURIComponent(window.location.pathname);
  window.location.href = `${loginUrl}?next=${next}`;
  return null;
}

async function logout() {
  try {
    await fetch("/auth/logout", { method: "POST", credentials: "include" });
  } catch (_) { /* ignore — cookies still cleared on server attempt */ }
  window.location.href = "/nai-ui/login.html";
}

// Expose for inline scripts in HTML pages.
window.bindAuthForm           = bindAuthForm;
window.requireAuthOrRedirect  = requireAuthOrRedirect;
window.logout                 = logout;
