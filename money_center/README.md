# Money Center

Track, control, and forecast revenue for every income-generating asset in the WheellsVerse ecosystem.

## Structure

```
money_center/
├── __init__.py
├── config.yaml          ← Port, paths, SSD volume
├── registry.py          ← Load/save/validate/backup functions
├── assets.json          ← 7 seed assets (edit with CLI or dashboard)
├── assets.backup.json   ← Auto-created before every write
├── cli.py               ← Rich CLI (all commands)
├── dashboard.py         ← Flask web dashboard (port 7777)
├── logs/
│   ├── money_center.log ← All start/stop/error events
│   └── <asset_id>.log   ← Per-asset stdout/stderr
└── tests/
    └── test_registry.py ← Unit tests
```

## Setup

```bash
cd /Users/jhonwheeler/wheellsverse_bots

# Install dependencies (already in venv)
pip install rich flask pyyaml

# Verify SSD is mounted
ls /Volumes/Wheellsverse
```

## CLI Usage

```bash
cd money_center

# List all assets
python cli.py list

# Full detail card
python cli.py show narai

# Start an asset (background process)
python cli.py start wheellsverse_bots

# Stop an asset (with confirmation)
python cli.py stop wheellsverse_bots

# Status table (all assets)
python cli.py status

# Revenue forecast grouped by category
python cli.py report

# Add a new asset (interactive)
python cli.py add

# Edit an asset field by field
python cli.py edit amazon_kdp

# Remove an asset (with confirmation)
python cli.py remove old_asset

# Tail last 50 log lines
python cli.py logs narai
python cli.py logs narai 100   # last 100 lines
```

## Web Dashboard

```bash
python dashboard.py
# → http://localhost:7777

python dashboard.py --port 8888  # custom port
python dashboard.py --debug       # dev mode with auto-reload
```

Dashboard features:
- Asset table with live status dots (🟢 running / ⚪ idle / 🟡 stopped / 🔴 error)
- Start / Stop / View / Logs buttons per asset
- Revenue total row (low / mid / high)
- Detail page with all metadata + log tail
- Add / Edit forms with validation
- Auto-backup before every write

## Config (`config.yaml`)

```yaml
root_path: /Users/jhonwheeler/wheellsverse_bots
dashboard_port: 7777
ssd_volume: /Volumes/Wheellsverse   # abort if not mounted
auto_backup: true
log_level: INFO
```

## Asset Schema

```json
{
  "id": "unique_slug",
  "name": "Readable name",
  "category": "bot | product | content | service | platform",
  "description": "One sentence.",
  "revenue_model": "subscription | ads | sales | affiliate | royalty | consulting | other",
  "monthly_estimate_usd": { "low": 0, "mid": 0, "high": 0 },
  "time_to_first_revenue_days": 30,
  "status": "idle | running | stopped | error",
  "last_run": null,
  "last_stop": null,
  "last_revenue_check": null,
  "total_revenue_usd": 0,
  "run_command": "python /path/to/run.py",
  "stop_command": "pkill -f 'run.py'",
  "working_dir": "/Volumes/Wheellsverse/...",
  "tags": [],
  "notes": "",
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

## Run Tests

```bash
cd /Users/jhonwheeler/wheellsverse_bots
python -m pytest money_center/tests/ -v
```

## Next Steps (prompt snippets)

**Update estimates with real data:**
> "Update assets.json with realistic estimates for each asset based on: [paste your real revenue data]"

**Add Stripe sync:**
> "Add a Stripe sync command that pulls real monthly revenue for Nexora and NarAI and updates total_revenue_usd."

**Email weekly report:**
> "Add a weekly report command that emails the revenue summary to wheelerjhonkevensd@gmail.com."

**Auto health check:**
> "Add a health check that pings each running asset every 5 minutes and flips status to error if the process is gone."

**Connect new asset:**
> "Add a new asset to the registry called <name>, category <cat>, revenue model <model>."
