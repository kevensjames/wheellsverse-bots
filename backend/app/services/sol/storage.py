"""Sol ROSCA ledger — SQLite over a single .db file.

Sidecar storage (data/sol/sol.db), mirroring the planning/failures/kg pattern:
isolated from the main Postgres DB so money-ledger schema changes carry zero
risk to user auth / billing. (A production ROSCA would graduate this to Postgres
for stronger durability + concurrency; the API here is written so that swap is
mechanical.)

MONEY IS ALWAYS INTEGER CENTS. Never floats — float sums drift. The Dwolla
client converts cents → "200.00" only at the API boundary.

Five tables:
  circles        — a savings circle (N members, fixed contribution, rotating payout)
  members        — a person in a circle; join_order = payout position
  cycles         — one round of a circle; recipient_member_id gets the pool
  contributions  — one member's payment in one cycle (mirrors a Dwolla transfer)
  payouts        — the disbursement to the recipient in one cycle
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# backend/app/services/sol/storage.py → parents[4] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
SOL_DB_PATH = Path(
    os.environ.get("KAI_SOL_DB_PATH", str(_REPO_ROOT / "data" / "sol" / "sol.db"))
)
SOL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ─── status vocab ────────────────────────────────────────────────────
CIRCLE_STATUSES = ("forming", "active", "completed", "cancelled")
MEMBER_STATUSES = ("invited", "verified", "active", "delinquent", "removed")
# "skipped" = collection closed but the recipient forfeited (delinquent); the
# pool rolled forward, no payout. Terminal like "paid", so the circle advances.
CYCLE_STATUSES = ("pending", "collecting", "collected", "paid", "failed", "skipped")
TRANSFER_STATUSES = ("pending", "processing", "processed", "failed", "returned")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── data models ─────────────────────────────────────────────────────
@dataclass(slots=True)
class Circle:
    id: int
    name: str
    contribution_cents: int
    member_target: int
    status: str = "forming"
    fee_bps: int = 0
    # Forfeited-pool accumulator: when a cycle's recipient is delinquent, the
    # collected pool rolls forward and is added to the next successful payout.
    rollover_cents: int = 0
    created_at: str | None = None
    activated_at: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Member:
    id: int
    circle_id: int
    name: str
    email: str | None = None
    dwolla_customer_id: str | None = None
    funding_source_href: str | None = None
    join_order: int | None = None
    status: str = "invited"
    created_at: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Cycle:
    id: int
    circle_id: int
    cycle_number: int
    recipient_member_id: int | None = None
    status: str = "pending"
    scheduled_date: str | None = None
    opened_at: str | None = None
    paid_at: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Contribution:
    id: int
    cycle_id: int
    member_id: int
    amount_cents: int
    status: str = "pending"
    dwolla_transfer_url: str | None = None
    retry_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Payout:
    id: int
    cycle_id: int
    recipient_member_id: int
    amount_cents: int
    status: str = "pending"
    dwolla_transfer_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─── connection + schema ─────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS circles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contribution_cents INTEGER NOT NULL,
    member_target INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'forming',
    fee_bps INTEGER NOT NULL DEFAULT 0,
    rollover_cents INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    circle_id INTEGER NOT NULL REFERENCES circles(id),
    name TEXT NOT NULL,
    email TEXT,
    dwolla_customer_id TEXT,
    funding_source_href TEXT,
    join_order INTEGER,
    status TEXT NOT NULL DEFAULT 'invited',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(circle_id, join_order)
);
CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    circle_id INTEGER NOT NULL REFERENCES circles(id),
    cycle_number INTEGER NOT NULL,
    recipient_member_id INTEGER REFERENCES members(id),
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_date TEXT,
    opened_at TEXT,
    paid_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(circle_id, cycle_number)
);
CREATE TABLE IF NOT EXISTS contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL REFERENCES cycles(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    dwolla_transfer_url TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(cycle_id, member_id)
);
CREATE TABLE IF NOT EXISTS payouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL REFERENCES cycles(id),
    recipient_member_id INTEGER NOT NULL REFERENCES members(id),
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    dwolla_transfer_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(cycle_id)
);
CREATE INDEX IF NOT EXISTS idx_members_circle ON members(circle_id);
CREATE INDEX IF NOT EXISTS idx_cycles_circle ON cycles(circle_id);
CREATE INDEX IF NOT EXISTS idx_contrib_cycle ON contributions(cycle_id);
-- UNIQUE (partial) so a Dwolla transfer href resolves to exactly one row — the
-- webhook finders use fetchone(). NULLs are allowed (many rows pre-transfer).
CREATE UNIQUE INDEX IF NOT EXISTS idx_contrib_transfer ON contributions(dwolla_transfer_url)
    WHERE dwolla_transfer_url IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_payout_transfer ON payouts(dwolla_transfer_url)
    WHERE dwolla_transfer_url IS NOT NULL;
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(SOL_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    # busy_timeout is per-connection: the scheduler daemon thread and request
    # threads both write, so a second writer waits-and-retries instead of failing
    # instantly with "database locked". (WAL itself is a persistent DB property
    # set once in init_db, not re-issued per connection.)
    c.execute("PRAGMA busy_timeout = 5000")
    try:
        yield c
    finally:
        c.close()


def _migrate(c: sqlite3.Connection) -> None:
    """Idempotent column adds for ledgers created before a column existed.
    SQLite has no ADD COLUMN IF NOT EXISTS, so we tolerate the duplicate error."""
    for table, col, ddl in (
        ("circles", "rollover_cents", "INTEGER NOT NULL DEFAULT 0"),
    ):
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    # Upgrade pre-existing non-UNIQUE transfer indexes to UNIQUE (partial). Drop
    # then recreate; tolerate a legacy duplicate href rather than brick startup.
    for tbl in ("contrib", "payout"):
        table = "contributions" if tbl == "contrib" else "payouts"
        try:
            c.execute(f"DROP INDEX IF EXISTS idx_{tbl}_transfer")
            c.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{tbl}_transfer "
                      f"ON {table}(dwolla_transfer_url) WHERE dwolla_transfer_url IS NOT NULL")
        except sqlite3.OperationalError as e:
            logger.warning("sol: could not make idx_%s_transfer UNIQUE (%s); "
                           "leaving non-unique", tbl, e)
            c.execute(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_transfer "
                      f"ON {table}(dwolla_transfer_url)")


def init_db() -> None:
    with _conn() as c:
        # WAL is a persistent database-level property — set it once at startup so
        # readers don't block the writer (and we don't re-issue it on every open).
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(_SCHEMA)
        _migrate(c)


init_db()


# ─── circles ─────────────────────────────────────────────────────────
def create_circle(name: str, contribution_cents: int, member_target: int,
                   fee_bps: int = 0) -> Circle:
    if contribution_cents <= 0:
        raise ValueError("contribution_cents must be positive")
    if member_target < 2:
        raise ValueError("member_target must be >= 2")
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO circles(name, contribution_cents, member_target, status, "
            "fee_bps, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (name, contribution_cents, member_target, "forming", fee_bps, now, now),
        )
        return get_circle(cur.lastrowid)  # type: ignore[arg-type]


def get_circle(circle_id: int) -> Circle:
    with _conn() as c:
        row = c.execute("SELECT * FROM circles WHERE id=?", (circle_id,)).fetchone()
    if not row:
        raise KeyError(f"circle {circle_id} not found")
    return Circle(**dict(row))


def list_circles(status: str | None = None) -> list[Circle]:
    q, args = "SELECT * FROM circles", ()
    if status:
        q += " WHERE status=?"; args = (status,)
    q += " ORDER BY id DESC"
    with _conn() as c:
        return [Circle(**dict(r)) for r in c.execute(q, args).fetchall()]


def set_circle_status(circle_id: int, status: str, *, activated: bool = False) -> None:
    if status not in CIRCLE_STATUSES:
        raise ValueError(f"bad circle status {status!r}")
    now = _now()
    with _conn() as c:
        if activated:
            c.execute("UPDATE circles SET status=?, activated_at=COALESCE(activated_at,?), "
                      "updated_at=? WHERE id=?", (status, now, now, circle_id))
        else:
            c.execute("UPDATE circles SET status=?, updated_at=? WHERE id=?",
                      (status, now, circle_id))


def set_rollover(circle_id: int, cents: int) -> None:
    """Set the forfeited-pool accumulator (absolute value, not delta)."""
    if cents < 0:
        raise ValueError("rollover_cents cannot be negative")
    with _conn() as c:
        c.execute("UPDATE circles SET rollover_cents=?, updated_at=? WHERE id=?",
                  (cents, _now(), circle_id))


# ─── members ─────────────────────────────────────────────────────────
def add_member(circle_id: int, name: str, email: str | None = None,
               dwolla_customer_id: str | None = None,
               funding_source_href: str | None = None, status: str = "invited") -> Member:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO members(circle_id, name, email, dwolla_customer_id, "
            "funding_source_href, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (circle_id, name, email, dwolla_customer_id, funding_source_href, status, now, now),
        )
        return get_member(cur.lastrowid)  # type: ignore[arg-type]


def get_member(member_id: int) -> Member:
    with _conn() as c:
        row = c.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    if not row:
        raise KeyError(f"member {member_id} not found")
    return Member(**dict(row))


def list_members(circle_id: int, status: str | None = None) -> list[Member]:
    q = "SELECT * FROM members WHERE circle_id=?"
    args: tuple = (circle_id,)
    if status:
        q += " AND status=?"; args = (circle_id, status)
    q += " ORDER BY COALESCE(join_order, 1e9), id"
    with _conn() as c:
        return [Member(**dict(r)) for r in c.execute(q, args).fetchall()]


def update_member(member_id: int, **fields: Any) -> Member:
    allowed = {"name", "email", "dwolla_customer_id", "funding_source_href",
               "join_order", "status"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "status" in sets and sets["status"] not in MEMBER_STATUSES:
        raise ValueError(f"bad member status {sets['status']!r}")
    if not sets:
        return get_member(member_id)
    sets["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in sets)
    with _conn() as c:
        c.execute(f"UPDATE members SET {cols} WHERE id=?", (*sets.values(), member_id))
    return get_member(member_id)


# ─── cycles ──────────────────────────────────────────────────────────
def create_cycle(circle_id: int, cycle_number: int, recipient_member_id: int | None,
                 scheduled_date: str | None = None, status: str = "collecting") -> Cycle:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO cycles(circle_id, cycle_number, recipient_member_id, status, "
            "scheduled_date, opened_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (circle_id, cycle_number, recipient_member_id, status, scheduled_date, now, now),
        )
        return get_cycle(cur.lastrowid)  # type: ignore[arg-type]


def get_cycle(cycle_id: int) -> Cycle:
    with _conn() as c:
        row = c.execute("SELECT * FROM cycles WHERE id=?", (cycle_id,)).fetchone()
    if not row:
        raise KeyError(f"cycle {cycle_id} not found")
    return Cycle(**dict(row))


def list_cycles(circle_id: int) -> list[Cycle]:
    with _conn() as c:
        return [Cycle(**dict(r)) for r in c.execute(
            "SELECT * FROM cycles WHERE circle_id=? ORDER BY cycle_number", (circle_id,)
        ).fetchall()]


def set_cycle_status(cycle_id: int, status: str, *, paid: bool = False) -> None:
    if status not in CYCLE_STATUSES:
        raise ValueError(f"bad cycle status {status!r}")
    now = _now()
    with _conn() as c:
        if paid:
            c.execute("UPDATE cycles SET status=?, paid_at=COALESCE(paid_at,?), updated_at=? "
                      "WHERE id=?", (status, now, now, cycle_id))
        else:
            c.execute("UPDATE cycles SET status=?, updated_at=? WHERE id=?",
                      (status, now, cycle_id))


# ─── contributions ───────────────────────────────────────────────────
def create_contribution(cycle_id: int, member_id: int, amount_cents: int) -> Contribution:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO contributions(cycle_id, member_id, amount_cents, status, "
            "created_at, updated_at) VALUES(?,?,?,?,?,?)",
            (cycle_id, member_id, amount_cents, "pending", now, now),
        )
        return get_contribution(cur.lastrowid)  # type: ignore[arg-type]


def get_contribution(contribution_id: int) -> Contribution:
    with _conn() as c:
        row = c.execute("SELECT * FROM contributions WHERE id=?", (contribution_id,)).fetchone()
    if not row:
        raise KeyError(f"contribution {contribution_id} not found")
    return Contribution(**dict(row))


def list_contributions(cycle_id: int) -> list[Contribution]:
    with _conn() as c:
        return [Contribution(**dict(r)) for r in c.execute(
            "SELECT * FROM contributions WHERE cycle_id=? ORDER BY id", (cycle_id,)
        ).fetchall()]


def find_contribution_by_transfer(transfer_url: str) -> Contribution | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM contributions WHERE dwolla_transfer_url=?",
                        (transfer_url,)).fetchone()
    return Contribution(**dict(row)) if row else None


def update_contribution(contribution_id: int, **fields: Any) -> Contribution:
    allowed = {"status", "dwolla_transfer_url", "retry_count"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "status" in sets and sets["status"] not in TRANSFER_STATUSES:
        raise ValueError(f"bad transfer status {sets['status']!r}")
    if not sets:
        return get_contribution(contribution_id)
    sets["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in sets)
    with _conn() as c:
        c.execute(f"UPDATE contributions SET {cols} WHERE id=?",
                  (*sets.values(), contribution_id))
    return get_contribution(contribution_id)


def claim_contribution(contribution_id: int, expect: str = "pending") -> bool:
    """Atomically move a contribution out of `expect` (default 'pending') into
    'processing'. Returns True only for the caller that wins the transition —
    the single-statement conditional UPDATE is the lock. The winner (and ONLY
    the winner) may then fire the ACH debit, so a double-click/concurrent collect
    can't debit the same member twice."""
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "UPDATE contributions SET status='processing', updated_at=? "
            "WHERE id=? AND status=?", (now, contribution_id, expect))
        return cur.rowcount == 1


# ─── payouts ─────────────────────────────────────────────────────────
def create_payout(cycle_id: int, recipient_member_id: int, amount_cents: int) -> Payout:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO payouts(cycle_id, recipient_member_id, amount_cents, status, "
            "created_at, updated_at) VALUES(?,?,?,?,?,?)",
            (cycle_id, recipient_member_id, amount_cents, "pending", now, now),
        )
        return get_payout(cur.lastrowid)  # type: ignore[arg-type]


def get_payout(payout_id: int) -> Payout:
    with _conn() as c:
        row = c.execute("SELECT * FROM payouts WHERE id=?", (payout_id,)).fetchone()
    if not row:
        raise KeyError(f"payout {payout_id} not found")
    return Payout(**dict(row))


def get_payout_for_cycle(cycle_id: int) -> Payout | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM payouts WHERE cycle_id=?", (cycle_id,)).fetchone()
    return Payout(**dict(row)) if row else None


def find_payout_by_transfer(transfer_url: str) -> Payout | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM payouts WHERE dwolla_transfer_url=?",
                        (transfer_url,)).fetchone()
    return Payout(**dict(row)) if row else None


def update_payout(payout_id: int, **fields: Any) -> Payout:
    allowed = {"status", "dwolla_transfer_url"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "status" in sets and sets["status"] not in TRANSFER_STATUSES:
        raise ValueError(f"bad transfer status {sets['status']!r}")
    if not sets:
        return get_payout(payout_id)
    sets["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in sets)
    with _conn() as c:
        c.execute(f"UPDATE payouts SET {cols} WHERE id=?", (*sets.values(), payout_id))
    return get_payout(payout_id)


def claim_payout(payout_id: int, expect: str = "pending") -> bool:
    """Atomically move a payout out of `expect` into 'processing'. Returns True
    only for the winner — so a double-clicked /payout can't credit the recipient
    twice. Mirror of claim_contribution."""
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "UPDATE payouts SET status='processing', updated_at=? "
            "WHERE id=? AND status=?", (now, payout_id, expect))
        return cur.rowcount == 1
