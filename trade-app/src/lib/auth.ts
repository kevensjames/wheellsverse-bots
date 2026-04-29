/**
 * JWT storage. localStorage is fine for a v1 dashboard — we accept the XSS
 * trade-off in exchange for working refreshes across tabs and survival across
 * page reloads. If we later need stricter security, swap to httpOnly cookies
 * served by the backend.
 */
const TOKEN_KEY = "wv_access_token";
const REFRESH_KEY = "wv_refresh_token";

export function setTokens(access: string, refresh?: string): void {
  localStorage.setItem(TOKEN_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
}

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}
