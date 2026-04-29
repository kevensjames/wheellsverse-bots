import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { login } from "../api/auth";

export function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login({ email, password });
      navigate("/dashboard");
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string }>;
      setError(ax.response?.data?.detail ?? "Invalid email or password");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-md py-12">
      <Card>
        <h1 className="text-xl font-semibold">Log in</h1>
        <p className="mt-1 text-sm text-[var(--color-fg-muted)]">
          Welcome back. Sign in to view today's predictions.
        </p>
        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <Field
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            autoFocus
            required
          />
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            required
            minLength={8}
          />
          {error && (
            <div className="rounded border border-[var(--color-sell)]/40 bg-[var(--color-sell)]/10 px-3 py-2 text-sm text-[var(--color-sell)]">
              {error}
            </div>
          )}
          <Button type="submit" loading={loading} className="w-full">
            Log in
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-[var(--color-fg-muted)]">
          New here?{" "}
          <Link to="/signup" className="text-[var(--color-accent)] hover:underline">
            Create an account
          </Link>
        </p>
      </Card>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  ...rest
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <label className="block">
      <span className="block text-xs font-medium uppercase tracking-wide text-[var(--color-fg-muted)]">
        {label}
      </span>
      <input
        {...rest}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-fg)] focus:border-[var(--color-accent)] focus:outline-none"
      />
    </label>
  );
}
