import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { fetchSubscription } from "../api/billing";

/**
 * Stripe redirects here after a successful Checkout. The webhook may or may
 * not have arrived yet — we poll /billing/subscription every 1.5s until we
 * see status=active, then auto-redirect to /dashboard.
 */
export function BillingSuccess() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const sub = useQuery({
    queryKey: ["subscription"],
    queryFn: fetchSubscription,
    refetchInterval: (q) =>
      q.state.data?.status === "active" ? false : 1500,
  });

  useEffect(() => {
    if (sub.data?.status === "active") {
      qc.invalidateQueries({ queryKey: ["predictions"] });
      const t = setTimeout(() => navigate("/dashboard"), 1500);
      return () => clearTimeout(t);
    }
  }, [sub.data?.status, navigate, qc]);

  const active = sub.data?.status === "active";

  return (
    <div className="mx-auto max-w-md py-12">
      <Card>
        <h1 className="text-xl font-semibold">
          {active ? "🎉 You're on Pro" : "Provisioning your subscription…"}
        </h1>
        <p className="mt-2 text-sm text-[var(--color-fg-muted)]">
          {active ? (
            <>Redirecting to your dashboard…</>
          ) : (
            <>
              We're confirming your payment with Stripe. This usually takes a few
              seconds. Don't refresh.
            </>
          )}
        </p>
        {active ? (
          <Button className="mt-6 w-full" onClick={() => navigate("/dashboard")}>
            Go to dashboard
          </Button>
        ) : (
          <Link
            to="/dashboard"
            className="mt-6 inline-block text-sm text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]"
          >
            Skip and go to dashboard
          </Link>
        )}
      </Card>
    </div>
  );
}
