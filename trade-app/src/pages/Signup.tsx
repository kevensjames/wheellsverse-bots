import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { signup } from "../api/auth";

export function Signup() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await signup({
        email,
        password,
        full_name: fullName || undefined,
      });
      navigate("/dashboard");
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string | unknown }>;
      const detail = ax.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Could not create account");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-md py-12">
      <Card>
        <h1 className="text-xl font-semibold">Create your account</h1>
        <p className="mt-1 text-sm text-[var(--color-fg-muted)]">
          Free tier · 3 predictions per day · no credit card required.
        </p>
        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <Field label="Full name (optional)" value={fullName} onChange={setFullName} />
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
            placeholder="At least 8 characters"
          />
          {error && (
            <div className="rounded border border-[var(--color-sell)]/40 bg-[var(--color-sell)]/10 px-3 py-2 text-sm text-[var(--color-sell)]">
              {error}
            </div>
          )}
          <Button type="submit" loading={loading} className="w-full">
            Create account
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-[var(--color-fg-muted)]">
          Already have an account?{" "}
          <Link to="/login" className="text-[var(--color-accent)] hover:underline">
            Log in
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
