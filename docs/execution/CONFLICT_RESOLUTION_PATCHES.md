# Conflict Resolutions (preserved, not reconstructed)

The authoritative preservation of every conflict resolution is the integration
commit **`40fdf90662900f7a56dc0d39eae372014c20186f`** (base `2fe6e46`). To see the
exact resolved bytes:

```bash
git show 40fdf90:backend/app/main.py        | grep '^from app.routers import'
git show 40fdf90:backend/requirements.txt
git show 40fdf90:backend/alembic/versions/0008_add_kai_swe_tasks.py
git diff 2fe6e46 40fdf90 -- backend/.env.example
```

All four conflicts were **additive** — no line from any PR was dropped or rewritten;
the resolution is the union.

## 1. `backend/app/main.py` — router import line

`#40` adds `admin_code_intel`, `#41` adds `admin_swe`, `#42` adds `admin_swe_tasks`, all to
the single `from app.routers import ...` line. Resolution = one line containing **all three**
plus the pre-existing modules (verified present in `40fdf90`):

```
from app.routers import ..., admin_code_intel, ..., admin_swe, admin_swe_tasks, ...
```

The matching `app.include_router(...)` blocks are non-overlapping and merged without conflict.

## 2. `backend/.env.example`

`#40`, `#41`, `#42`, `#48` each append distinct config blocks (code-intel, SWE runtime, SWE
agent scopes, dependency notes). Resolution = keep every block. No key defined twice.

## 3. `backend/requirements.txt`

`#40` adds the tree-sitter block; `#48` adds the PyYAML block. They landed at the same
location. Resolution = both blocks kept:

```
tree-sitter>=0.25,<0.27
tree-sitter-language-pack>=1.13,<2
...
PyYAML==6.0.2
```

## 4. Migration collision — `0007` × 2 → `0008`

`#40` introduced `0007_add_kai_code_chunks` (down_revision `0006`) and `#42` introduced
`0007_add_kai_swe_tasks` (down_revision `0006`) — two heads off `0006`, so
`alembic upgrade head` would fail with "Multiple head revisions are present."

Resolution: **`#42`'s migration renumbered** (no applied production history is rewritten —
neither migration is applied anywhere yet):

- file `0007_add_kai_swe_tasks.py` → `0008_add_kai_swe_tasks.py`
- `revision = "0008_add_kai_swe_tasks"`
- `down_revision = "0007_add_kai_code_chunks"` (was `0006_add_kai_api_keys`)

Verified on real PostgreSQL: `0006 → 0007_add_kai_code_chunks → 0008_add_kai_swe_tasks`
applies in order, `0008` downgrades to `0007` and re-upgrades cleanly. Single head, no
dangling revisions.

**If you use Method 1 (GitHub UI merge):** when merging `#42` after `#40`, apply this rename
in the conflict resolution (or cherry-pick it from `40fdf90`). The verifier
(`scripts/verify_post_merge.py`) will FAIL loudly if two heads survive.
