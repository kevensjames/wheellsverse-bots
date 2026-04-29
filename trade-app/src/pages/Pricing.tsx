import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { fetchSubscription, startCheckout, type PlanCode } from "../api/billing";

type Tier = {
  code: "free" | PlanCode;
  name: string;
  price: string;
  features: string[];
  cta: string;
  highlight?: boolean;
};

const TIERS: Tier[] = [
  {
    code: "free",
    name: "Free",
    price: "$0",
    features: [
      "3 predictions per day",
      "Today's BUY/SELL/HOLD signals",
      "30-day public win-rate stats",
    ],
    cta: "Current plan",
  },
  {
    code: "pro",
    name: "Pro",
    price: "$19/mo",
    features: [
      "Unlimited predictions",
      "All asset classes (stocks + crypto)",
      "Per-symbol prediction history",
      "Priority API rate limits",
    ],
    cta: "Subscribe",
    highlight: true,
  },
  {
    code: "elite",
    name: "Elite",
    price: "$49/mo",
    features: [
      "Everything in Pro",
      "SMS alerts on high-conviction signals",
      "Early access to new model versions",
    ],
    cta: "Subscribe",
  },
];

export function Pricing() {
  const subQuery = useQuery({
    queryKey: ["subscription"],
    queryFn: fetchSubscription,
  });
  const currentPlan = subQuery.data?.plan_code ?? "free";

  const [busyCode, setBusyCode] = useState<PlanCode | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubscribe(code: PlanCode) {
    setError(null);
    setBusyCode(code);
    try {
      const url = await startCheckout(code);
      window.location.assign(url);
    } catch {
      setError("Could not start checkout. Try again in a moment.");
      setBusyCode(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Pricing</h1>
        <p className="mt-1 text-sm text-[var(--color-fg-muted)]">
          Cancel anytime. Test cards work in dev — see the README.
        </p>
      </div>

      {error && (
        <div className="rounded border border-[var(--color-sell)]/40 bg-[var(--color-sell)]/10 px-3 py-2 text-sm text-[var(--color-sell)]">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {TIERS.map((t) => {
          const isCurrent = t.code === currentPlan;
          return (
            <Card
              key={t.code}
              className={
                t.highlight
                  ? "border-[var(--color-accent)]"
                  : ""
              }
            >
              <div className="flex items-baseline justify-between">
                <h2 className="text-lg font-semibold">{t.name}</h2>
                {t.highlight && (
                  <span className="rounded bg-[var(--color-accent)]/15 px-2 py-0.5 text-xs text-[var(--color-accent)]">
                    Popular
                  </span>
                )}
              </div>
              <div className="mt-2 text-3xl font-semibold">{t.price}</div>
              <ul className="mt-4 space-y-2 text-sm text-[var(--color-fg-muted)]">
                {t.features.map((f) => (
                  <li key={f} className="flex gap-2">
                    <span className="text-[var(--color-accent)]">✓</span>
                    {f}
                  </li>
                ))}
              </ul>
              <div className="mt-6">
                {t.code === "free" ? (
                  <Button variant="secondary" className="w-full" disabled>
                    {isCurrent ? "Current plan" : "Free tier"}
                  </Button>
                ) : isCurrent ? (
                  <Button variant="secondary" className="w-full" disabled>
                    Current plan
                  </Button>
                ) : (
                  <Button
                    className="w-full"
                    loading={busyCode === t.code}
                    onClick={() => handleSubscribe(t.code as PlanCode)}
                  >
                    Subscribe
                  </Button>
                )}
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
