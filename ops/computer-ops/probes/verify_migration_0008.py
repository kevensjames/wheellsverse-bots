"""Migration 0008 verification on disposable databases.

Checks the things a migration review actually has to answer: does it apply, does it
create what it claims, do the constraints do their job, does the downgrade restore a
usable schema, and can it be re-applied afterwards. It also checks unrelated rows are
untouched, because "the migration worked" and "the migration was safe" are different
questions.

The downgrade is deliberately PARTIAL (indexes only, tables retained). This script does
not paper over that -- it asserts the tables REMAIN and reports the downgrade as
compatibility-restoring rather than schema-restoring. Labelling a partial downgrade as a
successful rollback is exactly the kind of claim that gets believed in an incident.

    python3 ops/computer-ops/probes/verify_migration_0008.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "..", "..", "backend"))
DB = f"kai_mig_test_{uuid.uuid4().hex[:8]}"
URL = f"postgresql://localhost:5432/{DB}"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def psql(sql: str, db: str = DB) -> str:
    r = subprocess.run(["psql", "-d", db, "-tAc", sql], capture_output=True, text=True)
    if r.returncode != 0:
        return f"ERROR: {r.stderr.strip()[:200]}"
    return r.stdout.strip()


def alembic(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": URL, "APP_ENV": "test",
           "SECRET_KEY": "t", "SESSION_SIGNING_SECRET": "t", "API_KEY": "t"}
    return subprocess.run(["alembic", *args], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=300)


print(f"=== disposable database {DB} ===")
subprocess.run(["createdb", DB], check=True)
try:
    # --- upgrade to 0007, seed an unrelated row, then apply 0008 -------------
    up7 = alembic("upgrade", "0007_add_holding_action_nonces")
    check("upgrade 0000..0007 succeeds", up7.returncode == 0,
          up7.stderr.strip().splitlines()[-1][:120] if up7.returncode else "")
    if up7.returncode != 0:
        raise SystemExit(1)

    psql("INSERT INTO holding_action_nonces (jti, proposal_id, principal_id, environment, expires_at) "
         "VALUES ('unrelated-jti', 'p1', 'owner', 'test', now() + interval '1 hour')")
    before = psql("SELECT count(*) FROM holding_action_nonces")

    up8 = alembic("upgrade", "0008_add_kai_devices")
    check("upgrade 0007 -> 0008 succeeds", up8.returncode == 0,
          up8.stderr.strip().splitlines()[-1][:120] if up8.returncode else "")
    check("alembic head is 0008", psql(
        "SELECT version_num FROM alembic_version") == "0008_add_kai_devices")

    # --- structure ----------------------------------------------------------
    for table in ("kai_devices", "kai_device_pairings", "kai_device_nonces"):
        check(f"table {table} exists", psql(
            f"SELECT to_regclass('public.{table}') IS NOT NULL") == "t")

    cols = psql("SELECT string_agg(column_name, ',' ORDER BY column_name) "
                "FROM information_schema.columns WHERE table_name='kai_devices'")
    expected = {"arch", "confirmed_at", "created_at", "device_id", "enrolled_by",
                "granted_scopes", "key_rotated_at", "last_seen_at", "name", "os",
                "public_key", "revocation_reason", "revoked_at", "status"}
    check("kai_devices has the expected columns", expected <= set(cols.split(",")),
          f"missing {sorted(expected - set(cols.split(',')))}")

    types = dict(x.split("|") for x in psql(
        "SELECT column_name||'|'||data_type FROM information_schema.columns "
        "WHERE table_name='kai_devices' AND column_name IN "
        "('public_key','granted_scopes','created_at')").splitlines() if "|" in x)
    check("public_key is BYTEA (no private material, binary key)",
          types.get("public_key") == "bytea", types.get("public_key", "?"))
    check("granted_scopes is JSONB", types.get("granted_scopes") == "jsonb",
          types.get("granted_scopes", "?"))
    check("timestamps are timezone-aware",
          types.get("created_at") == "timestamp with time zone", types.get("created_at", "?"))

    idx = psql("SELECT string_agg(indexname, ',' ORDER BY indexname) FROM pg_indexes "
               "WHERE tablename LIKE 'kai_device%'")
    for want in ("kai_devices_status", "kai_device_pairings_expires", "kai_device_nonces_expires"):
        check(f"index {want} created", want in idx, idx)

    # --- constraints actually constrain ------------------------------------
    psql("INSERT INTO kai_devices (device_id,name,public_key,status) "
         "VALUES ('dev-a','A','\\x00','ACTIVE')")
    dup = psql("INSERT INTO kai_devices (device_id,name,public_key,status) "
               "VALUES ('dev-a','A2','\\x01','ACTIVE')")
    check("device_id is unique (duplicate identity refused)", dup.startswith("ERROR"),
          "duplicate accepted" if not dup.startswith("ERROR") else "")

    psql("INSERT INTO kai_device_nonces (device_id,nonce,expires_at) "
         "VALUES ('dev-a','n1', now() + interval '1 hour')")
    dupn = psql("INSERT INTO kai_device_nonces (device_id,nonce,expires_at) "
                "VALUES ('dev-a','n1', now() + interval '1 hour')")
    check("(device_id, nonce) is unique - replay cannot be re-burned",
          dupn.startswith("ERROR"), "duplicate accepted" if not dupn.startswith("ERROR") else "")
    # The same nonce for a DIFFERENT device must still be allowed: nonces are per-device.
    okn = psql("INSERT INTO kai_devices (device_id,name,public_key,status) VALUES "
               "('dev-b','B','\\x02','ACTIVE'); "
               "INSERT INTO kai_device_nonces (device_id,nonce,expires_at) "
               "VALUES ('dev-b','n1', now() + interval '1 hour')")
    check("the same nonce is allowed for a different device", not okn.startswith("ERROR"), okn[:80])

    psql("INSERT INTO kai_device_pairings (code_hash,device_name,created_by,expires_at) "
         "VALUES ('h1','X','owner', now() - interval '1 minute')")
    expired = psql("SELECT count(*) FROM kai_device_pairings WHERE expires_at <= now()")
    check("pairing expiry is queryable for sweeping", expired == "1", expired)
    dupp = psql("INSERT INTO kai_device_pairings (code_hash,device_name,created_by,expires_at) "
                "VALUES ('h1','Y','owner', now())")
    check("code_hash is unique (a code cannot be registered twice)", dupp.startswith("ERROR"))

    psql("UPDATE kai_devices SET status='REVOKED', granted_scopes='[]'::jsonb, "
         "revoked_at=now(), revocation_reason='test' WHERE device_id='dev-a'")
    rev = psql("SELECT status||'/'||granted_scopes::text FROM kai_devices WHERE device_id='dev-a'")
    check("revocation persists status AND cleared scopes", rev == "REVOKED/[]", rev)

    # --- unrelated data untouched ------------------------------------------
    after = psql("SELECT count(*) FROM holding_action_nonces")
    check("unrelated rows unchanged by 0008", before == after, f"{before} -> {after}")

    # --- downgrade ----------------------------------------------------------
    dn = alembic("downgrade", "0007_add_holding_action_nonces")
    check("downgrade 0008 -> 0007 succeeds", dn.returncode == 0,
          dn.stderr.strip().splitlines()[-1][:120] if dn.returncode else "")
    check("alembic head back at 0007",
          psql("SELECT version_num FROM alembic_version") == "0007_add_holding_action_nonces")

    idx_after = psql("SELECT count(*) FROM pg_indexes WHERE indexname IN "
                     "('kai_devices_status','kai_device_pairings_expires','kai_device_nonces_expires')")
    check("downgrade drops the indexes", idx_after == "0", idx_after)

    # THE HONEST PART: the tables remain, so this is NOT a schema restore.
    still = psql("SELECT count(*) FROM information_schema.tables WHERE table_name LIKE 'kai_device%'")
    check("downgrade RETAINS the tables (documented, intentional, NOT a full rollback)",
          still == "3", f"{still} tables remain")
    rows = psql("SELECT count(*) FROM kai_devices")
    check("device audit rows survive downgrade", rows == "2", rows)

    # --- re-upgrade after downgrade ----------------------------------------
    re8 = alembic("upgrade", "0008_add_kai_devices")
    check("re-upgrade after downgrade succeeds (idempotent DDL)", re8.returncode == 0,
          re8.stderr.strip().splitlines()[-1][:120] if re8.returncode else "")
    idx_re = psql("SELECT count(*) FROM pg_indexes WHERE indexname IN "
                  "('kai_devices_status','kai_device_pairings_expires','kai_device_nonces_expires')")
    check("indexes restored on re-upgrade", idx_re == "3", idx_re)
    check("existing rows preserved across downgrade+upgrade",
          psql("SELECT count(*) FROM kai_devices") == "2")
finally:
    subprocess.run(["dropdb", "--if-exists", DB], check=False)
    print(f"=== disposable database {DB} dropped ===")

bad = [n for n, ok, _ in results if not ok]
print(f"\n{sum(1 for _n, ok, _d in results if ok)}/{len(results)} migration checks passed")
print("RESULT:", "MIGRATION 0008 VERIFIED" if not bad else f"FAILED: {bad}")
sys.exit(1 if bad else 0)
