import { Link } from "react-router-dom";
import { Card } from "../components/Card";

export function BillingCancel() {
  return (
    <div className="mx-auto max-w-md py-12">
      <Card>
        <h1 className="text-xl font-semibold">No charge made</h1>
        <p className="mt-2 text-sm text-[var(--color-fg-muted)]">
          Your subscription wasn't created and your card wasn't charged. You can
          try again whenever you're ready.
        </p>
        <div className="mt-6 flex gap-3">
          <Link
            to="/pricing"
            className="rounded-md bg-[var(--color-accent)] px-3 py-2 text-sm text-white hover:bg-[var(--color-accent-hover)]"
          >
            Back to pricing
          </Link>
          <Link
            to="/dashboard"
            className="rounded-md border border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]"
          >
            Go to dashboard
          </Link>
        </div>
      </Card>
    </div>
  );
}
