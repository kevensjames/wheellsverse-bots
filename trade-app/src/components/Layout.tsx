import { Link, Outlet, useNavigate } from "react-router-dom";
import { clearTokens, isAuthenticated } from "../lib/auth";

export function Layout() {
  const navigate = useNavigate();
  const authed = isAuthenticated();

  function handleLogout() {
    clearTokens();
    navigate("/login");
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link to={authed ? "/dashboard" : "/"} className="flex items-center gap-2">
            <div className="h-7 w-7 rounded bg-[var(--color-accent)]" />
            <span className="font-semibold tracking-tight">
              Wheellsverse <span className="text-[var(--color-fg-muted)]">Trade</span>
            </span>
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            {authed ? (
              <>
                <Link to="/dashboard" className="hover:text-[var(--color-fg)] text-[var(--color-fg-muted)]">
                  Dashboard
                </Link>
                <Link to="/pricing" className="hover:text-[var(--color-fg)] text-[var(--color-fg-muted)]">
                  Pricing
                </Link>
                <button
                  onClick={handleLogout}
                  className="text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]"
                >
                  Sign out
                </button>
              </>
            ) : (
              <>
                <Link to="/login" className="hover:text-[var(--color-fg)] text-[var(--color-fg-muted)]">
                  Log in
                </Link>
                <Link
                  to="/signup"
                  className="rounded-md bg-[var(--color-accent)] px-3 py-1.5 text-white hover:bg-[var(--color-accent-hover)]"
                >
                  Sign up
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>
      <main className="flex-1">
        <div className="mx-auto max-w-6xl px-6 py-8">
          <Outlet />
        </div>
      </main>
      <footer className="border-t border-[var(--color-border)] py-6 text-center text-xs text-[var(--color-fg-muted)]">
        Wheellsverse Trade · rules-v1 model · for educational use only
      </footer>
    </div>
  );
}
