# WheellsVerse Neural-Mesh Theme

Custom Shopify OS 2.0 theme — futuristic neural-network aesthetic with live
animated background, glassmorphism panels, Orbitron typography.

## Structure
```
neural-mesh/
├── assets/         theme.css, theme.js (neural canvas animation)
├── config/         settings_schema.json + settings_data.json
├── layout/         theme.liquid + password.liquid
├── locales/        en.default.json
├── sections/       header, footer, hero, featured-collection, main-product, ...
├── snippets/       card-product
└── templates/      index, product, collection, cart, blog, article, page,
                    search, 404, gift_card, password,
                    customers/{login, register, account, order, ...}
```

## Customizations baked in
- Hero copy: "Built for the operator class."
- Announcement bar: real running offer ("AI STOCK ALERTS — $19/MO")
- Featured collections wired to `ai-tools-templates` + `all`
- 404: "Signal lost." copy
- Login: "Welcome back, operator."
- Cart empty state: "Initialize transaction..."
- 2 color presets: Default + High contrast
- Brand colors: cyan #22d3ee + blue #3b82f6 (Neural-Mesh signature)

## Re-build the upload zip
```bash
python3 /tmp/build_customized_theme.py
# zip lands at /tmp/wheellsverse-neural-mesh.zip
```

## Upload to Shopify
Shopify Admin → Online Store → Themes → Add theme → Upload zip file.
Drop `wheellsverse-neural-mesh.zip` from `/tmp`.
