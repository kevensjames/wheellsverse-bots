import axios, { type AxiosError, type AxiosInstance } from "axios";
import { clearTokens, getAccessToken } from "../lib/auth";

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/**
 * Single shared axios instance. Two interceptors:
 *  1. request — attaches Bearer token from localStorage if present.
 *  2. response — on 401, clears the token and redirects to /login.
 *
 * 402 is intentionally NOT redirected — pages decide how to render the
 * upgrade prompt (RateLimitBanner) inline.
 */
export const api: AxiosInstance = axios.create({ baseURL });

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err: AxiosError) => {
    const status = err.response?.status;
    if (status === 401) {
      clearTokens();
      // Avoid redirect loops if we're already on /login
      if (!window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    }
    return Promise.reject(err);
  },
);

/** Type for the 402 detail shape sent by /predictions/* */
export type RateLimitDetail = {
  error: string;
  limit: number;
  plan: string;
  action: string;
  upgrade_url: string;
};

/** Narrow an axios error into a 402 RateLimitDetail, or null if it isn't one. */
export function asRateLimit(err: unknown): RateLimitDetail | null {
  const ax = err as AxiosError<{ detail: RateLimitDetail }>;
  if (ax?.response?.status === 402 && ax.response.data?.detail) {
    return ax.response.data.detail;
  }
  return null;
}
