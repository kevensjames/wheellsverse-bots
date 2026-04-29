import clsx from "clsx";
import type { Signal } from "../api/predictions";

const styles: Record<Signal, string> = {
  BUY: "bg-[var(--color-buy)]/15 text-[var(--color-buy)] border-[var(--color-buy)]/30",
  SELL: "bg-[var(--color-sell)]/15 text-[var(--color-sell)] border-[var(--color-sell)]/30",
  HOLD: "bg-[var(--color-hold)]/15 text-[var(--color-hold)] border-[var(--color-hold)]/30",
};

export function SignalBadge({ signal }: { signal: Signal }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide",
        styles[signal],
      )}
    >
      {signal}
    </span>
  );
}
