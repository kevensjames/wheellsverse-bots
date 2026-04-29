import { useQuery } from "@tanstack/react-query";
import { Card } from "../components/Card";
import { RateLimitBanner } from "../components/RateLimitBanner";
import { SignalBadge } from "../components/SignalBadge";
import { fetchToday, type Prediction } from "../api/predictions";
import { fetchSubscription } from "../api/billing";
import { asRateLimit } from "../api/client";

export function Dashboard() {
  const subQuery = useQuery({
    queryKey: ["subscription"],
    queryFn: fetchSubscription,
    staleTime: 60_000,
  });

  const todayQuery = useQuery({
    queryKey: ["predictions", "today"],
    queryFn: () => fetchToday(),
    retry: (failureCount, err) => {
      // 402 is a known signal — don't retry. Other errors get one retry.
      return asRateLimit(err) ? false : failureCount < 1;
    },
  });

  const limit = asRateLimit(todayQuery.error);

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Today's signals</h1>
        {subQuery.data && (
          <div className="text-sm text-[var(--color-fg-muted)]">
            Plan:{" "}
            <span className="font-medium text-[var(--color-fg)]">
              {subQuery.data.plan_name}
            </span>{" "}
            · {subQuery.data.predictions_per_day}/day
          </div>
        )}
      </div>

      {limit && <RateLimitBanner detail={limit} />}

      <Card className="p-0 overflow-hidden">
        {todayQuery.isLoading ? (
          <div className="p-8 text-center text-sm text-[var(--color-fg-muted)]">
            Loading…
          </div>
        ) : todayQuery.error && !limit ? (
          <div className="p-8 text-center text-sm text-[var(--color-sell)]">
            Couldn't load predictions. Try again in a moment.
          </div>
        ) : todayQuery.data && todayQuery.data.length > 0 ? (
          <PredictionsTable rows={todayQuery.data} />
        ) : !limit ? (
          <div className="p-8 text-center text-sm text-[var(--color-fg-muted)]">
            No predictions yet today. Check back after the next prediction run.
          </div>
        ) : null}
      </Card>
    </div>
  );
}

function PredictionsTable({ rows }: { rows: Prediction[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="bg-[var(--color-surface-2)] text-xs uppercase tracking-wide text-[var(--color-fg-muted)]">
        <tr>
          <th className="px-4 py-3 text-left">Symbol</th>
          <th className="px-4 py-3 text-left">Signal</th>
          <th className="px-4 py-3 text-right">Confidence</th>
          <th className="px-4 py-3 text-right">Target</th>
          <th className="px-4 py-3 text-right">Stop</th>
          <th className="px-4 py-3 text-right">Horizon</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((p) => (
          <tr
            key={p.id}
            className="border-t border-[var(--color-border)] hover:bg-[var(--color-surface-2)]/40"
          >
            <td className="px-4 py-3 font-mono">{p.asset_symbol}</td>
            <td className="px-4 py-3">
              <SignalBadge signal={p.signal} />
            </td>
            <td className="px-4 py-3 text-right tabular-nums">
              {p.confidence.toFixed(1)}%
            </td>
            <td className="px-4 py-3 text-right tabular-nums">
              {p.target_price !== null ? p.target_price.toFixed(2) : "—"}
            </td>
            <td className="px-4 py-3 text-right tabular-nums">
              {p.stop_loss !== null ? p.stop_loss.toFixed(2) : "—"}
            </td>
            <td className="px-4 py-3 text-right text-[var(--color-fg-muted)]">
              {p.horizon_hours}h
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
