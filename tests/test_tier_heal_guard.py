"""The tier-heal job must never demote a COMPED account.

For weeks this job demoted the operator's own profile every night at 04:00 and fired a
Telegram alert reading "Check whether webhooks are dropping customer.subscription.deleted
events." No webhook was ever involved. The operator profile is granted tier='ultra' by
backend/app/routers/admin_chat.py on every /admin/kai-chat call — deliberately, "so a stray
DB edit can't silently downgrade" — and it has no Stripe subscription because the owner does
not pay themselves. Two subsystems fighting over one row, with the alert blaming a third.

The fix restricts the job to accounts actually provisioned through Stripe. This test pins
that guard by executing the REAL SQL, read out of the script rather than copied, so deleting
the guard fails here instead of silently at 04:00 in production.

The SQL is parsed from the file rather than imported: importing the script would execute its
module-level .env loading and mutate os.environ.
"""
import re
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "heal_tier_mirror.py"


def _heal_sql() -> str:
    src = SCRIPT.read_text()
    m = re.search(r'^HEAL_SQL = """(.*?)"""', src, re.S | re.M)
    assert m, "HEAL_SQL constant not found — did the script change shape?"
    return m.group(1)


def test_the_guard_is_present_in_the_real_sql():
    assert "stripe_customer_id IS NOT NULL" in _heal_sql()


def _fixture_db():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE profiles (
            id TEXT PRIMARY KEY, email TEXT, tier TEXT, stripe_customer_id TEXT
        );
        CREATE TABLE subscriptions (user_id TEXT, status TEXT);

        -- the comped operator: paid tier, NEVER provisioned through Stripe
        INSERT INTO profiles VALUES ('op',  'op@x',  'ultra', NULL);
        -- a real ex-customer: provisioned through Stripe, subscription canceled
        INSERT INTO profiles VALUES ('ex',  'ex@x',  'pro',   'cus_EX');
        -- a real paying customer: provisioned through Stripe, subscription active
        INSERT INTO profiles VALUES ('cur', 'cur@x', 'max',   'cus_CUR');
        -- an ordinary free user
        INSERT INTO profiles VALUES ('free','free@x','free',  NULL);

        INSERT INTO subscriptions VALUES ('ex',  'canceled');
        INSERT INTO subscriptions VALUES ('cur', 'active');
        """
    )
    return db


@pytest.mark.skipif(sqlite3.sqlite_version_info < (3, 35),
                    reason="UPDATE ... RETURNING requires sqlite 3.35+")
def test_the_real_sql_demotes_only_stripe_provisioned_accounts():
    db = _fixture_db()
    demoted = {row[0] for row in db.execute(_heal_sql()).fetchall()}

    # The whole point: the comped operator survives.
    assert "op" not in demoted, "the comped operator profile was demoted — the 04:00 bug is back"
    # The capability is preserved: a genuine cancelled customer is still demoted.
    assert demoted == {"ex"}, f"expected only the cancelled Stripe customer, got {demoted}"

    tiers = dict(db.execute("SELECT id, tier FROM profiles").fetchall())
    assert tiers["op"] == "ultra"      # comped grant intact
    assert tiers["ex"] == "free"       # genuinely demoted
    assert tiers["cur"] == "max"       # active subscriber untouched
    assert tiers["free"] == "free"


@pytest.mark.skipif(sqlite3.sqlite_version_info < (3, 35),
                    reason="UPDATE ... RETURNING requires sqlite 3.35+")
def test_without_the_guard_the_operator_would_be_demoted():
    """Proves the guard is what saves the operator — not some other clause.

    Without this, a refactor could drop the guard while the test above still passed for an
    unrelated reason, and nobody would learn until the next 04:00 alert.
    """
    unguarded = _heal_sql().replace("AND stripe_customer_id IS NOT NULL", "")
    db = _fixture_db()
    demoted = {row[0] for row in db.execute(unguarded).fetchall()}
    assert "op" in demoted, "fixture no longer reproduces the original bug — it has lost its point"
