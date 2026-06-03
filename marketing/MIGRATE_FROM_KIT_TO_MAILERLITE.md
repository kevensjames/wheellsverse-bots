# Path C — Migrate from Kit free tier to MailerLite free tier

**Status:** planned, not built. Flip to this when Path B (SMTP via Gmail) starts hitting limits or you want proper deliverability/automation without upgrading Kit.

## Why MailerLite

| Feature | Kit free | MailerLite free | Path B (current) |
|---|---|---|---|
| Subscribers | 1,000 | 1,000 | unlimited (DB-backed) |
| Sequences / automations | ✗ paywalled | ✓ included | ✓ via SMTP + cron |
| Per-subscriber timing | ✗ no | ✓ yes | ✓ yes |
| Deliverability | high (Kit IPs) | high (MailerLite IPs) | medium (Gmail SMTP, your reputation) |
| Daily send cap | ∞ (within sub cap) | 12,000/mo | ~500/day Gmail personal, ~2,000/day Workspace |
| Required code change | none (just upgrade) | new ESP client | already done |
| Cost | $0 → $15/mo at scale | $0 → $10/mo at scale | $0 |

**Trigger to switch:**
- Daily sends approaching 400 → MailerLite (avoid Gmail rate-limit lockout)
- Spam complaints / inbox placement issues → MailerLite (their reputation > yours)
- You want a UI to edit emails outside the repo → MailerLite

Until then, Path B is fine and free.

## API at a glance

- Base URL: `https://connect.mailerlite.com/api`
- Auth: `Authorization: Bearer <MAILERLITE_API_KEY>`
- Generate key: MailerLite dashboard → Integrations → API → Generate new token (free tier supported)

The endpoints we need:

| Operation | Endpoint | Notes |
|---|---|---|
| Upsert subscriber | `POST /subscribers` | body `{"email":..., "fields": {"name":...}}` — idempotent by email |
| Get subscriber | `GET /subscribers/{email}` | accepts email or ID |
| Create group (≈ Kit tag) | `POST /groups` | body `{"name":"kdp"}` |
| Add subscriber to group | `POST /subscribers/{id}/groups/{group_id}` | empty body |
| Create automation | UI ONLY | MailerLite free does NOT expose POST /automations either — same wall as Kit |

**The catch:** MailerLite free tier also blocks automation *creation* via API — but the UI can create them on the free plan. Unlike Kit, where the free plan blocks sequences entirely (both API and UI), MailerLite gives you free UI access to build automations and then API access to trigger them.

So the migration plan is:
1. Build the 3 automations once in MailerLite's UI (5 min each)
2. Use the API to add subscribers + tag them + trigger automation entry

## Code swap-in points

The Toodle code was deliberately built so the ESP is replaceable. To migrate:

### 1. New client module

Create `core/mailerlite.py` mirroring `core/kit.py`'s shape:

```python
class MailerLiteClient:
    def is_configured(self) -> bool: ...
    def upsert_subscriber(self, email: str, fields: dict | None = None) -> dict: ...
    def list_groups(self) -> list[dict]: ...                  # the tag analog
    def create_group(self, name: str) -> dict: ...
    def add_subscriber_to_group(self, sub_id: int, group_id: int) -> dict: ...
    def trigger_automation(self, automation_id: int, sub_id: int) -> dict: ...
```

Use `Authorization: Bearer ${MAILERLITE_API_KEY}` header. Same dry-run gate pattern as `core/kit.py`.

### 2. Capture route

In `narai/api/routes/toodle.py`, replace the imports/calls:

```python
# BEFORE
from core.kit import get_kit
client = get_kit()
...
sub_result = await asyncio.to_thread(client.upsert_subscriber, ...)
tag_id = await resolver.tag_id(tag_name)
await asyncio.to_thread(client.tag_subscriber, tag_id, subscriber_id)

# AFTER
from core.mailerlite import get_mailerlite
client = get_mailerlite()
...
sub_result = await asyncio.to_thread(client.upsert_subscriber, ..., fields={"name": req.first_name})
group_id = await resolver.group_id(tag_name)
await asyncio.to_thread(client.add_subscriber_to_group, group_id, subscriber_id)
```

The `KitResolver` becomes `MailerLiteResolver` with `group_id()` instead of `tag_id()`.

### 3. Cadence (no change)

The `TOODLE_CADENCE` dict and the `ToodleEmailQueue` table stay exactly the same — they don't care which ESP is active. The dispatcher (`core/toodle_dispatcher.py`) is already ESP-agnostic; it reads paste files and sends via SMTP.

**Decision: keep the SMTP dispatcher OR delegate to MailerLite's automation engine?**
- **Keep SMTP** (recommended initially): your timing logic is already correct; MailerLite is just the audience store. Lowest risk migration.
- **Delegate to MailerLite automations**: drop the cron + dispatcher entirely once MailerLite automations are built in their UI. Cleaner long-term but requires re-pasting all 10 emails into MailerLite's automation builder.

### 4. Env vars

Add to `.env.example`:
```
MAILERLITE_API_KEY=
MAILERLITE_API_BASE=https://connect.mailerlite.com/api
MAILERLITE_DRY_RUN=true
MAILERLITE_GROUP_KDP_NAME=kdp
MAILERLITE_GROUP_WELCOME_NAME=welcome
```

### 5. Feature flag for cutover

Add to `narai/api/routes/toodle.py` at module level:

```python
ESP_BACKEND = os.getenv("TOODLE_ESP_BACKEND", "kit").lower()  # kit | mailerlite

def _get_esp_client():
    if ESP_BACKEND == "mailerlite":
        from core.mailerlite import get_mailerlite
        return get_mailerlite()
    from core.kit import get_kit
    return get_kit()
```

Flip `TOODLE_ESP_BACKEND=mailerlite` in `.env` and the capture route uses the new ESP without code changes elsewhere.

## Estimated effort

- Build `core/mailerlite.py` mirroring kit.py: 30 min
- Build resolver + capture-route swap: 15 min
- Build a `scripts/toodle_mailerlite_check.py` verifier: 10 min
- Manual: create MailerLite account, generate key, set up 3 automations in UI: 30 min
- Smoke test: 15 min

**Total: ~2 hours of focused work.**

Don't do it until Path B starts hurting. The whole point of Path B is buying you time at $0.
