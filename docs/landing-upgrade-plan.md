# WheellsVerse Landing Page Upgrade — Plan v1

**Scope:** rewrite `frontend/landing_page.html` only. No build step. No framework change. Ship in 1–2 days.

**Goal:** turn the homepage into a dark, cinematic showcase that converts visitors — centerpiece is a 3D NarAI humanoid that reacts to the user, plus live surfaces for Nexora, Sol, Store, and the Blog.

---

## What stays

- Static HTML + Netlify deploy (no Next.js migration)
- All other pages: `dashboard.html`, `chat.html`, `pricing.html`, `signup.html`, `login.html`, `nexora/*`, `sol/*`, `store/*`, `blog/*`
- `netlify.toml` routing (root → `landing_page.html`)
- Current color tokens: `--cyan #00d4ff`, `--purple #a855f7`, `--green #00ff88`, `--gold #ffd700`
- SEO meta, TikTok verification meta, sitemap

## What changes

Only `frontend/landing_page.html`. Everything else is untouched in this pass.

---

## Tech (all via CDN — no npm install)

| Library | Purpose | Load via |
|---------|---------|----------|
| Three.js | 3D scene | `<script type="importmap">` + `unpkg.com/three@0.160.0` |
| GLTFLoader | Load robot `.glb` | same importmap |
| OrbitControls | Optional subtle orbit | same importmap |
| No framework | — | vanilla JS modules |

Robot model: one CC0 humanoid `.glb` from Sketchfab, hosted at `frontend/assets/narai.glb` (swappable file — custom NarAI later = drop-in replace).

---

## Page sections (top to bottom)

### 1. Sticky nav
Keep current nav structure; tighten spacing, add "Enter the System" primary CTA.

### 2. Hero — particle field + headline
- Full-screen black with animated canvas particle field
- Headline: **"70 bots. One system. Infinite output."**
- Sub: "WheellsVerse — the AI wealth ecosystem built by J.K. Blaze."
- CTAs: `[Enter the System]` (→ `/dashboard.html`) and `[Meet NarAI]` (scrolls to §3)
- **Live counter bar** (4 tiles): Active Bots · Tasks Today · Uptime · Revenue Tracked
  - Hybrid data: animated placeholder + `fetchStats()` stub with TODO for user

### 3. NarAI — 3D humanoid centerpiece
- Left column: Three.js canvas, 1:1 square on desktop, full-width on mobile
  - Robot idle-breathes, head rotates subtly with cursor
  - Click a capability chip → robot plays short animation + chat card slides in
- Right column: chat box
  - Mic toggle uses Web Speech API (no backend required for v1)
  - Text input wired to `/api/nx/chat` (already proxied to Railway)
- Capability chips (clickable): `Signals` · `Memory` · `Voice` · `Code` · `Prediction`

### 4. Dashboard preview strip
- 3 glass cards showing: bot grid snapshot, recent runs feed, revenue sparkline
- CTA: "See the full dashboard →" (→ `/dashboard.html`)

### 5. Modules grid — the products
4 cards, equal weight. Each: icon, one-line pitch, hover mockup, deep link.

| Card | Pitch | Link |
|------|-------|------|
| **Nexora** | Creator platform — fans tip, creators ship | `/nexora` |
| **Sol** | Trusted-circle savings (ROSCA, reinvented) | `/sol` |
| **Store** | Prompt Bible + AI tools for builders | `/store` |
| **Blog** | Daily AI + money signals, free | `/blog` |

### 6. Blog strip
Horizontal scroll of 6 newest posts pulled from a static JSON manifest (I'll add `blog/manifest.json`).

### 7. Founder — J.K. Blaze
Photo, one-paragraph bio (your words), socials row.

### 8. Footer
Sitemap · Legal · Newsletter · Socials · © 2026 WheellsVerse

---

## Build order

1. Backup current file → `landing_page.backup.html`
2. Scaffold new `landing_page.html` with section skeletons + CSS variables
3. Hero particle field + live counters (with `fetchStats()` TODO)
4. Download a CC0 humanoid GLB → `frontend/assets/narai.glb`
5. Three.js scene + capability chip interactions
6. Dashboard preview cards + modules grid
7. Blog strip (manifest-driven) + founder + footer
8. Mobile tune-up (hero stacks, canvas 16:9, nav collapse)
9. Show screenshot, wait for your feedback
10. Deploy to Netlify only after you approve

---

## Your learning contribution — `fetchStats()`

I scaffold the whole hero, counters, and animation. **You write ~8 lines** in one function:

```js
// landing_page.html — inside <script>
// TODO(Jhon): wire this to your Railway API.
// Endpoint idea: https://api.wheellsverse.com/stats
// Expected JSON shape: { bots: 70, tasks: 1247, uptime: 99.9, revenue: 12400 }
async function fetchStats() {
  // your code here
  // hint: use fetch(), parse JSON, call updateCounters(data)
  // on error, keep the placeholder numbers (don't break the UI)
}
```

**Why this matters:** this is the one place where the page talks to *your* system. The decision is: which endpoint, which fields, how to handle failure. That shapes how the hero feels when the Railway API has a hiccup.

---

## Performance budget

- Page weight under 400 KB (excluding GLB model)
- GLB model ≤ 2 MB (compressed, Draco if available)
- Lighthouse: Performance 85+, Accessibility 95+, SEO 95+
- First Contentful Paint under 1.5s on 4G

## Non-goals for this pass

- No Next.js rewrite
- No CMS
- No changes to `nexora/`, `sol/`, `store/`, `blog/` pages
- No new Railway endpoints (reuse what exists)
- No custom NarAI model (swap later)

---

## AMENDMENT v1.1 — Figma-reference structure (2026-04-22)

Dark theme stays. Four structural changes applied:

1. **Hamburger nav** — top-right 2-bar icon on both desktop and mobile. Opens full-screen dark overlay with stacked items (Blogs / Nexora / Sol / Shop / Log in) each with a → arrow. Bottom of overlay: primary CTA "Enter the System". Close ✕ top right.
2. **Hero typography** — one thought per line, bigger/bolder. Three stacked rows: "70 bots." / "One system." / "One founder." Space Grotesk 700+.
3. **NarAI 3D glow frame** — cyan accent border around the robot canvas with soft outer glow (like the King Tomo reference). Tap the robot = wave/tilt animation.
4. **Nav cleanup** — desktop nav links removed. Only logo (left) + hamburger (right). Cleanest possible top bar.

All hamburger routes verified to exist. No 404s.

---

## Open questions for you before I start

1. **Founder bio** — paste 2–3 sentences you want on the page, or I draft from memory (J.K. Blaze, WheellsVerse, music + AI)
2. **Newsletter provider** — Beehiiv, ConvertKit, Mailchimp, or leave a "coming soon" stub?
3. **Revenue counter** — show a real number or hide this tile for now? (Sensitive to reveal publicly.)

Answer 1/2/3 and I start with step 1 (backup + scaffold).
