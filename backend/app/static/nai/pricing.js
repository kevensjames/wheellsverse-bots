// Pricing page → Stripe Checkout.
//
// Flow:
//   1. User clicks "Subscribe to Pro/Elite".
//   2. POST /billing/checkout with {plan_code} (cookie auth).
//   3. If 401 → redirect to signup, remember plan via localStorage so we can
//      auto-resume after they sign up.
//   4. If 200 → redirect to Stripe checkout_url.

const PENDING_PLAN_KEY = "nai_pending_plan";
const error = document.getElementById("error");

function showError(msg) {
  error.textContent = msg;
  error.classList.add("visible");
}
function clearError() {
  error.textContent = "";
  error.classList.remove("visible");
}

async function startCheckout(planCode) {
  clearError();
  const buttons = document.querySelectorAll("button[data-plan]");
  buttons.forEach(b => b.disabled = true);

  try {
    const resp = await fetch("/billing/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ plan_code: planCode }),
    });

    if (resp.status === 401) {
      localStorage.setItem(PENDING_PLAN_KEY, planCode);
      window.location.href = "/kai-ui/signup.html?next=" +
        encodeURIComponent("/kai-ui/pricing.html");
      return;
    }

    if (!resp.ok) {
      let detail = `${resp.status} ${resp.statusText}`;
      try {
        const data = await resp.json();
        if (data && data.detail) detail = data.detail;
      } catch (_) { /* non-JSON body */ }
      showError(`Checkout failed: ${detail}`);
      return;
    }

    const data = await resp.json();
    if (!data.checkout_url) {
      showError("Server returned no checkout_url");
      return;
    }
    // Hand off to Stripe.
    window.location.href = data.checkout_url;
  } catch (err) {
    showError(`Network error: ${err.message || err}`);
  } finally {
    buttons.forEach(b => b.disabled = false);
  }
}

document.querySelectorAll("button[data-plan]").forEach(btn => {
  btn.addEventListener("click", () => startCheckout(btn.dataset.plan));
});

// Auto-resume: if the user just came back from signup with a pending plan,
// kick off checkout for them.
(function maybeResumePendingPlan() {
  const pending = localStorage.getItem(PENDING_PLAN_KEY);
  if (!pending) return;
  localStorage.removeItem(PENDING_PLAN_KEY);
  // Defer a tick so the page paints first.
  setTimeout(() => startCheckout(pending), 50);
})();
