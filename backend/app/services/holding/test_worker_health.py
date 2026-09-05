"""§119 worker-health normalization — observed-liveness / no-authority guard. Zero-framework (mirrors
test_registry.py). Heartbeats are in the status.list_workers shape; jobs in the worker_jobs.list_jobs shape.
Run (from backend/):  python3 -m app.services.holding.test_worker_health
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.capability.manifest import (CapabilityManifest as CM, CapabilityType as CT, Availability as AV,   # noqa: E402
                                              Certification as CE, ActivationMode as AM, WorkerProfile)
from app.services.capability.coding import CodingWorkerRouter, CodingTask       # noqa: E402
from app.services.holding import worker_health as wh                            # noqa: E402
from app.services.holding.worker_health import (normalize, normalize_worker, execution_authority, credential_present,  # noqa: E402
                                                router_health, STATES, LIVE_STATES, WORKER_HEALTH_VERSION)
from app.services.holding.self_model import FLAG_KEYS                          # noqa: E402

# ── fixtures ──────────────────────────────────────────────────────────────────────────────────────────
def _wp(provider, **kw):
    return WorkerProfile(coding_modes=["implement", "review"], headless_support=True, git_support=True,
                         tool_support=True, context_window=200000, model_provider=provider, **kw)

CLAUDE = CM(id="claude-code", name="Claude Code", type=CT.CODING_WORKER, availability=AV.AVAILABLE, certification=CE.CERTIFIED,
            activation=AM.ALWAYS_AVAILABLE, worker_profile=_wp("anthropic"))
CODEX = CM(id="codex", name="OpenAI Codex", type=CT.CODING_WORKER, availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL,
           worker_profile=_wp("openai"))
LOCAL = CM(id="local-w", name="Local worker", type=CT.CODING_CLI, availability=AV.AVAILABLE, certification=CE.CERTIFIED,
           activation=AM.ON_DEMAND, worker_profile=_wp(""))
QUAR = CM(id="bad-w", name="Quarantined worker", type=CT.CODING_WORKER, availability=AV.QUARANTINED, certification=CE.REJECTED,
          worker_profile=_wp(""))
OFFW = CM(id="off-w", name="Switched-off worker", type=CT.CODING_WORKER, availability=AV.AVAILABLE, certification=CE.CERTIFIED,
          activation=AM.DISABLED, worker_profile=_wp(""))
MCP = CM(id="context7", name="Context7 MCP", type=CT.MCP, availability=AV.AVAILABLE, certification=CE.CERTIFIED)   # no worker_profile
MANIFESTS = [CLAUDE, CODEX, LOCAL, QUAR, OFFW, MCP]
HB = [  # status.list_workers shape
    {"worker_id": "claude-code:host1", "host_id": "host1", "online": True, "current_job": None, "last_heartbeat_secs_ago": 5},
    {"worker_id": "runner-77", "host_id": "host2", "online": True, "current_job": 9, "last_heartbeat_secs_ago": 3},   # no catalog worker
]
JOBS = [{"id": 9, "status": "running", "worker": "local-w", "claimed_by": "local-w"},
        {"id": 10, "status": "succeeded", "worker": "claude-code", "claimed_by": "claude-code:host1"}]
OFF = {**{k: False for k in FLAG_KEYS}, "MONEY_MODE": "MOCK", "APP_ENV": "staging"}
A01 = {**OFF, "KAI_CAPABILITY_EXECUTION_ENABLED": True, "HOLDING_AUTONOMY_ENABLED": True}
A2 = {**A01, "KAI_A2_EXECUTION_ENABLED": True}
AUTH = {"anthropic": True, "openai": True}


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    def w(snap, wid):
        return next(x for x in snap["workers"] if x["worker"] == wid)

    def one(m, **kw):   # stopped=False = the §97 STOP record was READ and is RELEASED (the only authority-granting value)
        return normalize_worker(m, auth=kw.pop("auth", AUTH), flags=kw.pop("flags", OFF), stopped=kw.pop("stopped", False), **kw)

    snap = normalize(manifests=MANIFESTS, heartbeats=HB, jobs=JOBS, auth=AUTH, flags=OFF, stopped=False)

    # ── vocabulary, determinism, scope ────────────────────────────────────────────────────────────
    ck("same inputs -> byte-identical snapshot, versioned, the 7-state vocabulary",
       normalize(manifests=MANIFESTS, heartbeats=HB, jobs=JOBS, auth=AUTH, flags=OFF, stopped=False) == snap
       and snap["version"] == WORKER_HEALTH_VERSION == "1.1.0"
       and tuple(snap["states"]) == STATES == ("ONLINE", "IDLE", "BUSY", "DEGRADED", "AUTH_BLOCKED", "OFFLINE", "QUARANTINED"))
    ck("only coding-worker manifests (worker_profile) are workers; every state is in the vocabulary; counts partition",
       {x["worker"] for x in snap["workers"]} == {"claude-code", "codex", "local-w", "bad-w", "off-w"}
       and all(x["state"] in STATES for x in snap["workers"]) and sum(snap["counts"].values()) == len(snap["workers"]))

    # ── the normalization rules over OBSERVED signals ─────────────────────────────────────────────
    ck("QUARANTINED catalog -> QUARANTINED (§52), reason cites the catalog", w(snap, "bad-w")["state"] == "QUARANTINED"
       and "QUARANTINED" in w(snap, "bad-w")["reasons"][0] and w(snap, "bad-w")["sources"][0].startswith("capability.seed:bad-w"))
    ck("DISCOVERED (not runnable per catalog) -> OFFLINE even with a credential present",
       w(snap, "codex")["state"] == "OFFLINE" and "not runnable per catalog" in w(snap, "codex")["reasons"][0]
       and w(snap, "codex")["credential_present"] is True)
    ck("activation DISABLED -> OFFLINE", w(snap, "off-w")["state"] == "OFFLINE")
    ck("heartbeat online + no current job -> IDLE (heartbeat 'claude-code:host1' matched to claude-code)",
       w(snap, "claude-code")["state"] == "IDLE" and w(snap, "claude-code")["heartbeats"] == 1
       and "holding.status.list_workers" in w(snap, "claude-code")["sources"])
    ck("a live claimed/running job -> BUSY with the job count (succeeded jobs are not live)",
       w(snap, "local-w")["state"] == "BUSY" and w(snap, "local-w")["live_jobs"] == 1
       and "holding.worker_jobs.list_jobs" in w(snap, "local-w")["sources"])
    ck("heartbeat reporting a current job -> BUSY",
       one(CLAUDE, heartbeats=[{"worker_id": "claude-code", "online": True, "current_job": 4}])["state"] == "BUSY")
    ck("no credential for the provider AND nothing observed live -> AUTH_BLOCKED (env-key PRESENCE, labelled 'in this process')",
       one(CLAUDE, auth={"anthropic": False})["state"] == "AUTH_BLOCKED"
       and "no anthropic credential" in one(CLAUDE, auth={"anthropic": False})["reasons"][0]
       and "ANTHROPIC_API_KEY" in one(CLAUDE, auth={"anthropic": False})["reasons"][0]
       and "nothing observed live" in one(CLAUDE, auth={"anthropic": False})["reasons"][0]
       and one(CLAUDE, auth={"anthropic": False})["credential_scope"] == "in this process (runner env not observable)")
    # review M8: observation outranks inference — the runner's env is not this process's env
    busy_nocred = one(CLAUDE, auth={"anthropic": False}, heartbeats=[{"worker_id": "claude-code:host1", "online": True, "current_job": 4}])
    ck("M8: observed running job + no LOCAL credential -> BUSY (credential_present False kept as a separate labelled fact), NOT AUTH_BLOCKED",
       busy_nocred["state"] == "BUSY" and busy_nocred["credential_present"] is False
       and busy_nocred["credential_scope"] == "in this process (runner env not observable)"
       and any("runner env not observable" in r and "OBSERVED on the runner" in r for r in busy_nocred["reasons"]))
    ck("M8: heartbeat online (no job) + no local credential -> IDLE; probe passed + no local credential -> ONLINE",
       one(CLAUDE, auth={"anthropic": False}, heartbeats=HB)["state"] == "IDLE"
       and one(CLAUDE, auth={"anthropic": False}, health={"claude-code": True})["state"] == "ONLINE")
    ck("M8 does not weaken the observed negatives: a FAILED probe is still DEGRADED even with a heartbeat and no credential",
       one(CLAUDE, auth={"anthropic": False}, health={"claude-code": False}, heartbeats=HB)["state"] == "DEGRADED")
    ck("runtime health probe FAILED -> DEGRADED (the router's own `health` seam)",
       one(CLAUDE, health={"claude-code": False})["state"] == "DEGRADED"
       and one(CLAUDE, health={"claude-code": False}, heartbeats=HB)["state"] == "DEGRADED")
    ck("probe passed, no heartbeat plane -> ONLINE", one(CLAUDE, health={"claude-code": True})["state"] == "ONLINE")
    ck("catalog AVAILABLE + credential present but NOTHING observed live -> OFFLINE ('not OBSERVED live')",
       one(CLAUDE)["state"] == "OFFLINE" and "not OBSERVED live" in one(CLAUDE)["reasons"][0]
       and "credential present" in one(CLAUDE)["reasons"][0])
    ck("a local/unspecified provider needs no credential (None) and can be ONLINE",
       credential_present("") is None and credential_present("unknown-provider") is None
       and one(LOCAL, health={"local-w": True})["credential_present"] is None and one(LOCAL, health={"local-w": True})["state"] == "ONLINE")

    # ── §120: presence only — a credential VALUE never appears anywhere ──────────────────────────
    env = {"ANTHROPIC_API_KEY": "sk-ant-SECRET-VALUE-123"}
    ck("credential_present reads PRESENCE from the env map (True / False) and never the value",
       credential_present("anthropic", env) is True and credential_present("anthropic", {}) is False
       and credential_present("openai", env) is False
       and "SECRET-VALUE" not in json.dumps(snap) and "values never read" in " ".join(w(snap, "claude-code")["sources"]))

    # ── §119 ONLINE != authority: liveness never grants execution ─────────────────────────────────
    live_states = {one(CLAUDE, health={"claude-code": True})["state"], one(CLAUDE, heartbeats=HB)["state"],
                   one(LOCAL, jobs=JOBS)["state"]}
    ck("ONLINE / IDLE / BUSY workers all carry execution_authority NONE while the brakes are off",
       live_states == {"ONLINE", "IDLE", "BUSY"} and all(x["execution_authority"] == "NONE" for x in snap["workers"])
       and snap["execution_authority"] == "NONE" and all("never grants authority" in x["authority_note"] for x in snap["workers"]))
    ck("authority comes ONLY from the three brakes (STOP released): #1+#2 -> A0_A1_READ_ONLY, +#3 -> A2_PREPARE_ONLY, #3 alone -> NONE (fail-closed)",
       execution_authority(OFF, False) == "NONE" and execution_authority(A01, False) == "A0_A1_READ_ONLY"
       and execution_authority(A2, False) == "A2_PREPARE_ONLY"
       and execution_authority({**OFF, "KAI_A2_EXECUTION_ENABLED": True}, False) == "NONE" and execution_authority({}, False) == "NONE"
       and execution_authority(None, False) == "NONE")
    # review H2: §97 STOP is consulted — engaged OR unreadable (None) → NONE, whatever the brakes say
    ck("H2: STOP engaged -> execution_authority NONE even with all three brakes ON",
       execution_authority(A2, True) == "NONE" and execution_authority(A01, True) == "NONE")
    ck("H2: STOP unreadable (None) -> treated as engaged -> NONE; and NOT passing `stopped` is the same fail-closed default",
       execution_authority(A2, None) == "NONE" and execution_authority(A2) == "NONE")
    stopped_snap = normalize(manifests=MANIFESTS, heartbeats=HB, jobs=JOBS, auth=AUTH, flags=A2, stopped=True)
    unread_snap = normalize(manifests=MANIFESTS, heartbeats=HB, jobs=JOBS, auth=AUTH, flags=A2, stopped=None)
    ck("H2: snapshot under brakes-on + STOP engaged -> every worker NONE, stop_record_state ENGAGED; unreadable -> NONE + UNAVAILABLE (brakes' vocabulary)",
       all(x["execution_authority"] == "NONE" for x in stopped_snap["workers"]) and stopped_snap["execution_authority"] == "NONE"
       and stopped_snap["stop_record_state"] == "ENGAGED" and stopped_snap["stop_engaged"] is True
       and all(x["execution_authority"] == "NONE" for x in unread_snap["workers"]) and unread_snap["stop_record_state"] == "UNAVAILABLE"
       and unread_snap["stop_engaged"] is True and snap["stop_record_state"] == "RELEASED" and snap["stop_engaged"] is False
       and wh.stop_state(True) == "ENGAGED" and wh.stop_state(False) == "RELEASED" and wh.stop_state(None) == "UNAVAILABLE")
    ck("H2: STOP does not change the observed STATE (a BUSY worker stays BUSY) — it only removes authority",
       w(stopped_snap, "local-w")["state"] == "BUSY" and w(stopped_snap, "claude-code")["state"] == "IDLE")
    ck("an OFFLINE/AUTH_BLOCKED worker under brakes-on (STOP released) still reports the brake-derived class — state and authority are independent axes",
       one(CLAUDE, auth={"anthropic": False}, flags=A2)["state"] == "AUTH_BLOCKED"
       and one(CLAUDE, auth={"anthropic": False}, flags=A2)["execution_authority"] == "A2_PREPARE_ONLY")

    # ── composition: status.list_workers rows + CodingWorkerRouter ───────────────────────────────
    ck("runner rows that match no catalog worker surface under runner_plane (never attributed to a worker)",
       snap["runner_plane"] == [{"worker_id": "runner-77", "online": True, "current_job": 9}]
       and not any(x["heartbeats"] and x["worker"] != "claude-code" for x in snap["workers"]))
    task = CodingTask(description="fix", task_type="implement")
    workers = [CLAUDE, LOCAL]
    blocked = normalize(manifests=workers, auth={"anthropic": False}, health={"local-w": True}, flags=OFF)
    dec = CodingWorkerRouter().select(task, workers, health=router_health(blocked))
    ck("router_health(snapshot) feeds CodingWorkerRouter: AUTH_BLOCKED Claude is rejected as unhealthy, the live local worker is selected",
       router_health(blocked) == {"claude-code": False, "local-w": True}
       and ("claude-code", "worker unhealthy") in dec.rejected and dec.selected == "local-w")
    live = normalize(manifests=workers, auth=AUTH, health={"claude-code": True, "local-w": True}, flags=OFF)
    dec2 = CodingWorkerRouter().select(task, workers, health=router_health(live))
    ck("both observed live -> both eligible for the router (liveness feeds SELECTION, not authority)",
       dec2.rejected == [] and dec2.selected in ("claude-code", "local-w") and set(LIVE_STATES) == {"ONLINE", "IDLE", "BUSY"})
    ck("the same `health` dict drives both: probe FAILED -> DEGRADED here AND 'worker unhealthy' in the router",
       one(CLAUDE, health={"claude-code": False})["state"] == "DEGRADED"
       and ("claude-code", "worker unhealthy") in CodingWorkerRouter().select(task, [CLAUDE], health={"claude-code": False}).rejected)

    # ── live snapshot over the REAL catalog (DB-less: heartbeats/jobs fail soft, env probe is real) ─
    ls = wh.snapshot()
    ck("snapshot(): real coding-worker manifests, every state in the vocabulary, authority NONE under the real (all-off) flags",
       len(ls["workers"]) >= 5 and all(x["state"] in STATES for x in ls["workers"]) and ls["execution_authority"] == "NONE"
       and not any(x["state"] in LIVE_STATES for x in ls["workers"]))     # nothing is observed live in this runtime
    real_stop = wh.read_stop()      # DB-less run: the record is unreadable -> None -> treated as engaged
    ck("snapshot(): the §97 STOP record is READ via brakes.stop_record and reported in its vocabulary (never assumed RELEASED)",
       ls["stop_record_state"] in ("ENGAGED", "RELEASED", "UNAVAILABLE") and ls["stop_record_state"] == wh.stop_state(real_stop)
       and ls["stop_engaged"] is (real_stop is not False) and (real_stop is not None or ls["stop_record_state"] == "UNAVAILABLE"))

    # ── consolidation + purity ────────────────────────────────────────────────────────────────────
    src = Path(wh.__file__).read_text()
    ck("composes seed_registry, status.list_workers, worker_jobs.list_jobs, self_model._flags (the ONE flag reader), brakes.stop_record (the ONE STOP record)",
       all(s in src for s in ("from app.services.capability.seed import seed_registry", "from app.services.holding.status import list_workers",
                              "from app.services.holding.worker_jobs import list_jobs", "from app.services.holding.self_model import _flags",
                              "from app.services.holding.brakes import stop_record",
                              "from app.services.holding.brakes import ENGAGED, RELEASED, UNAVAILABLE")))
    ck("no LLM / network / clock / subprocess — liveness is read, never probed by side effect here",
       all(t not in src for t in ("datetime.now", "time.time", "openai", "ollama", "httpx", "requests", "subprocess",
                                  "capability.brain", "nai_brain")))

    n = len(res); ok = sum(res)
    print(f"\nWORKER HEALTH (§119) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
