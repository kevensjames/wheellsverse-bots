import { Link } from "react-router-dom";
import type { RateLimitDetail } from "../api/client";

export function RateLimitBanner({ detail }: { detail: RateLimitDetail }) {
  return (
    <div className="rounded-lg border border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 p-4 text-sm">
      <div className="font-semibold text-[var(--color-fg)]">
        You've hit your free-tier limit ({detail.limit}/day)
      </div>
      <div className="mt-1 text-[var(--color-fg-muted)]">{detail.action}</div>
      <Link
        to="/pricing"
        className="mt-3 inline-block rounded-md bg-[var(--color-accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--color-accent-hover)]"
      >
        Upgrade now
      </Link>
    </div>
  );
}
