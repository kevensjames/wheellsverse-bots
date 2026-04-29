import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card } from "../components/Card";
import { fetchStats } from "../api/predictions";

export function Landing() {
  const stats = useQuery({
    queryKey: ["predictions", "stats"],
    queryFn: fetchStats,
  });

  return (
    <div className="space-y-12 py-12">
      <section className="text-center">
        <h1 className="text-4xl font-semibold tracking-tight md:text-5xl">
          AI-graded BUY/SELL/HOLD signals,
          <br />
          delivered every hour.
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-[var(--color-fg-muted)]">
          Stocks and crypto, scored on RSI, MACD crossovers, and SMA trend.
          Free tier gives you 3 predictions a day. No credit card.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <Link
            to="/signup"
            className="rounded-md bg-[var(--color-accent)] px-5 py-3 text-sm font-medium text-white hover:bg-[var(--color-accent-hover)]"
          >
            Start free
          </Link>
          <Link
            to="/login"
            className="rounded-md border border-[var(--color-border)] px-5 py-3 text-sm text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]"
          >
            Log in
          </Link>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold">Live model stats (last 30 days)</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-4">
          <Stat
            label="Predictions"
            value={stats.data?.total_predictions.toLocaleString() ?? "—"}
          />
          <Stat
            label="BUY signals"
            value={stats.data?.by_signal.BUY?.toString() ?? "—"}
          />
          <Stat
            label="SELL signals"
            value={stats.data?.by_signal.SELL?.toString() ?? "—"}
          />
          <Stat
            label="Avg. confidence"
            value={
              stats.data ? `${stats.data.avg_confidence.toFixed(1)}%` : "—"
            }
          />
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <div className="text-xs uppercase tracking-wide text-[var(--color-fg-muted)]">
        {label}
      </div>
      <div className="mt-2 text-3xl font-semibold tabular-nums">{value}</div>
    </Card>
  );
}
