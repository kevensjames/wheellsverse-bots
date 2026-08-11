// Cloudflare Pages Function — apex → backend proxy.
//
// wheellsverse.com is a static Cloudflare Pages site; the KAI backend (bots,
// /admin dashboard, and every /api/* route) runs on Railway. Without this,
// wheellsverse.com/admin loads but its /api/* calls fall through to the static
// catch-all and return the marketing homepage — so the dashboard shows no data.
//
// This forwards /admin and /api/* to the Railway origin (server-side, same-origin
// to the browser — no CORS), and lets every other path serve as a static asset.
// Result: wheellsverse.com/admin === app.wheellsverse.com/admin.

const BACKEND = "https://grateful-flexibility-production.up.railway.app";

export async function onRequest(context) {
  const { request, next } = context;
  const url = new URL(request.url);
  const p = url.pathname;

  const proxied = p.startsWith("/api/") || p === "/admin" || p.startsWith("/admin/");
  if (!proxied) return next(); // static asset (marketing site, /sol, /blog, …)

  const headers = new Headers(request.headers);
  headers.delete("host"); // let fetch set Host for the Railway origin

  const init = { method: request.method, headers, redirect: "manual" };
  if (request.method !== "GET" && request.method !== "HEAD") init.body = request.body;

  const resp = await fetch(BACKEND + p + url.search, init);
  return new Response(resp.body, resp);
}
