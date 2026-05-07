# WheellsVerse Neural-Mesh Theme

Custom Shopify OS 2.0 theme — futuristic neural-network aesthetic with live
animated background, glassmorphism panels, Orbitron typography. Amazon-grade
shopper UX layered on top.

## Structure
```
neural-mesh/
├── assets/         theme.css.liquid (Liquid-templated CSS), theme.js
├── config/         settings_schema.json + settings_data.json
├── layout/         theme.liquid + password.liquid
├── locales/        en.default.json
├── sections/       header, footer, hero, mobile-nav, main-product,
│                   main-collection, featured-collection, premium-products,
│                   shop-by-category, recently-viewed, lead-banner,
│                   recommended-deals, you-may-like, email-capture, ...
├── snippets/       card-product, breadcrumbs, trust-badges, pixels,
│                   star-rating, mega-menu, qa-section, reviews-section,
│                   bundle-widget
└── templates/      index, product, collection, cart, blog, article, page,
                    search, 404, gift_card, password,
                    customers/{login, register, account, order, ...}
```

## Amazon-grade UX components

- **Mega-menu**: header "All" button opens a 6-tile category grid + trending
  rail. Wired in `snippets/mega-menu.liquid`.
- **Mobile bottom nav**: fixed Home/Shop/Search/Cart/Account bar on phones.
  `sections/mobile-nav.liquid` (auto-included via layout/theme.liquid).
- **Star ratings + sale badges** on every product card.
  `snippets/card-product.liquid` + `snippets/star-rating.liquid`.
- **Image hover-zoom** on product page (cursor lens + side pane, desktop only).
  Wired in `sections/main-product.liquid`.
- **Frequently bought together** bundle on PDP — picks 2 recommendations and
  adds all 3 to cart in one click. `snippets/bundle-widget.liquid`.
- **Q&A accordion** on PDP — metafield-driven, hides if empty.
  `snippets/qa-section.liquid`.
- **Reviews section** on PDP — metafield-driven, hides if empty. Compatible
  with Loox / Judge.me / Stamped that write into the `reviews` namespace.
  `snippets/reviews-section.liquid`.
- **Tracking pixels** (Meta + TikTok) — ID-driven via Theme Editor.
  `snippets/pixels.liquid`.

## Metafield contracts

The PDP components are honest by default — they only render when the merchant
has filled real data in via Shopify Admin → Settings → Custom data → Products.
Set up these definitions once, then fill per-product:

### Reviews (powers stars + reviews block)
| Namespace.key   | Type             | Example |
|-----------------|------------------|---------|
| `reviews.rating`| Decimal          | `4.7`   |
| `reviews.count` | Integer          | `132`   |
| `reviews.list`  | List of metaobjects (or JSON list) | `[{"author":"Sara K.","rating":5,"title":"Game-changer","body":"Used the AI tool template for 3 client projects last week — saved ~6 hours each.","date":"Apr 28, 2026","verified":true}, ...]` |

If you don't want to set these manually, install Loox or Judge.me and
configure their export to write into the `reviews` namespace.

### Q&A (powers Q&A accordion)
Two options — both supported by `snippets/qa-section.liquid`:

**A) JSON list (cleanest):**
| Namespace.key | Type | Example |
|---------------|------|---------|
| `qa.items` | List of single line text (JSON) | `[{"question":"Does this work for crypto too?","answer":"Yes — the templates cover both stocks and crypto signals."}, ...]` |

**B) Individual fields (no JSON tooling needed):**
| Namespace.key | Type | Example |
|---------------|------|---------|
| `qa.q1` | Single line text | `"Does this work on mobile?"` |
| `qa.a1` | Multi-line text  | `"Yes — the dashboard is fully responsive."` |
| `qa.q2`, `qa.a2`, ... up to `q6/a6` | as above | |

## Re-build the upload zip

```bash
cd themes/neural-mesh && \
  zip -r /tmp/wheellsverse-neural-mesh.zip . -x "*.DS_Store" "*.git*"
```

## Upload to Shopify
Shopify Admin → Online Store → Themes → Add theme → Upload zip file.
Drop `wheellsverse-neural-mesh.zip` from `/tmp`.

## Customizations baked in
- Hero copy: "Built for the operator class."
- Announcement bar: real running offer ("AI STOCK ALERTS — $19/MO")
- Featured collections wired to `ai-tools-templates`, `premium-picks`,
  `trending`, `all`
- 404: "Signal lost." copy
- Login: "Welcome back, operator."
- Cart empty state: "Initialize transaction..."
- 2 color presets: Default + High contrast
- Brand colors: cyan #22d3ee + blue #3b82f6 (Neural-Mesh signature)
