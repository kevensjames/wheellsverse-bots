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


# ── the promoter/demoter contract ────────────────────────────────────────────────────────────────
#
# Found by review on PR #83, and it was a real hole. The heal guard added above spares accounts with
# no `stripe_customer_id`, on the reasoning that a comped grant has no Stripe provenance. But the
# LIVE promoter — the inline `checkout.session.completed` handler in core/api.py, which is the only
# code that grants a paid tier (nai_subscription.py implements the full flow and is imported by
# nothing but its own test) — did not write `stripe_customer_id` either. So a real paying customer
# looked exactly like a comped grant, and since this job is the only demotion mechanism in the
# system, a cancellation would have left paid access in place forever.
#
# The two sides are now one contract: whatever column the demoter uses to recognise a Stripe-
# provisioned account, the promoter must write. These tests fail if either side drifts.

API = Path(__file__).resolve().parent.parent / "core" / "api.py"


def _narai_upgrade_node():
    """The `if narai_plan in (...)` branch that grants a paid tier, located structurally.

    core/api.py is ~16.5k lines. Calling ast.get_source_segment for every If node re-splits the
    whole file each time and took over two minutes; this narrows to candidate nodes by line range
    first (integer comparisons) and builds exactly one string.
    """
    import ast as _ast
    src = API.read_text()
    lines = src.splitlines()
    targets = [n for n, ln in enumerate(lines, 1) if "narai_plan in (" in ln]
    assert targets, "could not find the NarAI tier-upgrade branch in core/api.py"
    target = targets[0]
    tree = _ast.parse(src)
    best = None
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.If) or node.end_lineno is None:
            continue
        if node.lineno <= target <= node.end_lineno:
            if best is None or (node.end_lineno - node.lineno) < (best.end_lineno - best.lineno):
                best = node
    assert best is not None, "no enclosing If found for the tier-upgrade branch"
    return best, "\n".join(lines[best.lineno - 1:best.end_lineno])


def _provenance_assignments(node):
    """Every `<something>["stripe_customer_id"] = ...` inside the branch, with its ancestor chain."""
    import ast as _ast
    parents = {}
    for parent in _ast.walk(node):
        for child in _ast.iter_child_nodes(parent):
            parents[child] = parent
    found = []
    for n in _ast.walk(node):
        if not isinstance(n, _ast.Assign):
            continue
        for t in n.targets:
            if (isinstance(t, _ast.Subscript) and isinstance(t.slice, _ast.Constant)
                    and t.slice.value == "stripe_customer_id"):
                chain, cur = [], n
                while cur in parents:
                    cur = parents[cur]
                    chain.append(cur)
                found.append((n, chain))
    return found


def test_the_promoter_records_stripe_provenance():
    node, src = _narai_upgrade_node()
    assert _provenance_assignments(node), (
        "The live checkout handler grants a paid profiles.tier without recording "
        "stripe_customer_id. The heal job uses that column to tell a paying customer from a comped "
        "grant, so omitting it means a real customer who cancels keeps paid access forever."
    )


def test_the_demoter_uses_the_column_the_promoter_writes():
    """The contract: the discriminator must be written by the promoter and read by the demoter."""
    node, _ = _narai_upgrade_node()
    assert "stripe_customer_id" in _heal_sql(), "stripe_customer_id left the heal SQL"
    assert _provenance_assignments(node), "stripe_customer_id left the promoter"


def test_provenance_is_written_conditionally_not_unconditionally():
    """Writing the column unconditionally blanks a good id when Stripe omits `customer`.

    Checked STRUCTURALLY — an earlier version of this test looked for the substring "if
    stripe_customer" and a mutant that removed the guard survived it. The assignment must sit
    inside an `if`, nested within the upgrade branch.
    """
    import ast as _ast
    node, _ = _narai_upgrade_node()
    assigns = _provenance_assignments(node)
    assert assigns, "no stripe_customer_id assignment found at all"
    for assign, ancestors in assigns:
        guarded = any(isinstance(a, _ast.If) for a in ancestors[:-1]) or (
            len(ancestors) > 0 and isinstance(ancestors[0], _ast.If))
        assert guarded, (
            "stripe_customer_id is assigned unconditionally — a checkout payload with no "
            "`customer` field would blank a previously recorded id."
        )
