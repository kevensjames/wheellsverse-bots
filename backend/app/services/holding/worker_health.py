"""§119 worker health normalization — ONE vocabulary over the REAL worker signals:

    ONLINE / IDLE / BUSY / DEGRADED / AUTH_BLOCKED / OFFLINE / QUARANTINED

Sources (all existing, all injectable): the capability catalog's coding-worker manifests
(``capability.seed.seed_registry`` — the SAME manifests ``CodingWorkerRouter`` selects over), the
runner heartbeat plane (``status.list_workers``), the job queue (``worker_jobs.list_jobs``), an
optional runtime health probe map (the ``health`` dict ``CodingWorkerRouter.select`` already accepts),
credential PRESENCE per model provider (env presence only — never a value, §120), and the real
authority flags (``self_model._flags``).

Truth rules (§0 #16-19, §120): liveness must be OBSERVED — a worker with no heartbeat and no passing
probe is OFFLINE even when the catalog says AVAILABLE; a provider-backed worker with no credential in
THIS runtime is AUTH_BLOCKED regardless of its catalog history. ONLINE != authority: every row carries
``execution_authority`` derived from the three brakes, and it is "NONE" while they are off (§0 #12).
Pure/deterministic; testable as a plain ``python3`` script (mirrors test_registry.py).
"""
from __future__ import annotations

import functools
import os

from app.services.capability.manifest import Availability as AV, Certification as CE, ActivationMode as AM

WORKER_HEALTH_VERSION = "1.0.0"
STATES = ("ONLINE", "IDLE", "BUSY", "DEGRADED", "AUTH_BLOCKED", "OFFLINE", "QUARANTINED")
LIVE_STATES = ("ONLINE", "IDLE", "BUSY")      # OBSERVED live — selectable, still no authority

# Credential PRESENCE per model provider — env key NAMES only; a value is never read into the result (§120).
# The provider vocabulary is the catalog's own (WorkerProfile.model_provider on the real coding-worker
# manifests) — no second provider list lives here. Convention: <PROVIDER>_API_KEY; vendors whose CLIs
# read other names are aliased below.
_AUTH_ENV_ALIASES = {
    "anthropic": ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "github": ("GITHUB_TOKEN", "GH_TOKEN"),
}
_LIVE_JOB = ("claimed", "running")


@functools.lru_cache(maxsize=1)
def _known_providers() -> frozenset:
    """Providers declared by the REAL worker manifests (the ONE vocabulary, §119)."""
    from app.services.capability.seed import seed_registry
    return frozenset((m.worker_profile.model_provider or "").strip().lower()
                     for m in seed_registry().list() if getattr(m, "worker_profile", None)) - {""}


def auth_env_keys(provider: str) -> tuple:
    """Env key NAMES probed for ``provider``; () when no catalog worker declares that provider."""
    p = (provider or "").strip().lower()
    if p not in _known_providers():
        return ()
    return _AUTH_ENV_ALIASES.get(p, (f"{p.upper()}_API_KEY",))


def credential_present(provider: str, env=None):
    """True/False = a credential for ``provider`` is/is not present in the runtime env; None = the
    provider needs none (local / unspecified / not a catalog provider). Presence only — never the value (§120)."""
    keys = auth_env_keys(provider)
    if not keys:
        return None
    env = os.environ if env is None else env
    return any(bool(env.get(k)) for k in keys)


def execution_authority(flags: dict) -> str:
    """What a worker may EXECUTE right now, from the three brakes — independent of its liveness
    (§119 'ONLINE != authority'). Fail-closed: a missing flag is OFF."""
    f = flags or {}
    if not (f.get("KAI_CAPABILITY_EXECUTION_ENABLED") and f.get("HOLDING_AUTONOMY_ENABLED")):
        return "NONE"
    return "A2_PREPARE_ONLY" if f.get("KAI_A2_EXECUTION_ENABLED") else "A0_A1_READ_ONLY"


def _heartbeats_for(worker_id: str, heartbeats: list) -> list:
    """Runner rows that name this worker (exact id, or 'id:…' / 'id-…' runner naming)."""
    out = []
    for h in heartbeats or []:
        wid = str((h or {}).get("worker_id") or "")
        if wid == worker_id or wid.startswith(worker_id + ":") or wid.startswith(worker_id + "-"):
            out.append(h)
    return out


def normalize_worker(m, *, heartbeats=None, jobs=None, auth=None, health=None, flags=None) -> dict:
    """One worker → its §119 state + the observable reasons + sources. ``auth`` = {provider: bool}
    overrides the env probe (tests); ``health`` = {cap_id: bool} runtime probe (the router's seam)."""
    heartbeats, jobs, auth, health = heartbeats or [], jobs or [], auth or {}, health or {}
    wp = m.worker_profile
    provider = (wp.model_provider if wp else "") or ""
    cred = auth[provider] if provider in auth else credential_present(provider)
    hb = _heartbeats_for(m.id, heartbeats)
    live = [j for j in jobs if isinstance(j, dict) and j.get("status") in _LIVE_JOB
            and (j.get("worker") == m.id or j.get("claimed_by") == m.id)]
    online_hb = [h for h in hb if h.get("online")]
    reasons, sources = [], [f"capability.seed:{m.id} availability={m.availability.value} "
                            f"certification={m.certification.value} activation={m.activation.value}"]
    if m.availability == AV.QUARANTINED:
        state = "QUARANTINED"; reasons.append("catalog availability QUARANTINED (policy/health violation, §52)")
    elif (m.availability != AV.AVAILABLE or m.activation == AM.DISABLED
          or m.certification in (CE.EXTERNAL_BLOCKED, CE.REJECTED)):
        state = "OFFLINE"
        reasons.append(f"not runnable per catalog: availability={m.availability.value}, "
                       f"certification={m.certification.value}, activation={m.activation.value}")
    elif cred is False:
        state = "AUTH_BLOCKED"
        reasons.append(f"no {provider} credential present in this runtime "
                       f"(checked presence of {', '.join(auth_env_keys(provider)) or 'no known env key'})")
        sources.append("env presence probe (values never read)")
    elif health.get(m.id) is False:
        state = "DEGRADED"; reasons.append("runtime health probe FAILED"); sources.append("runtime health probe")
    elif live or any(h.get("current_job") for h in online_hb):
        state = "BUSY"
        reasons.append(f"{len(live)} live job(s) claimed/running" if live else "heartbeat reports a current job")
        sources += ["holding.worker_jobs.list_jobs"] + (["holding.status.list_workers"] if online_hb else [])
    elif online_hb:
        state = "IDLE"; reasons.append("heartbeat online, no current job"); sources.append("holding.status.list_workers")
    elif health.get(m.id) is True:
        state = "ONLINE"; reasons.append("runtime health probe passed (no heartbeat plane)"); sources.append("runtime health probe")
    else:
        state = "OFFLINE"
        reasons.append("no live heartbeat and no passing runtime probe — runnable per catalog"
                       + (" with credential present" if cred else "") + ", but not OBSERVED live")
    if cred is True:
        sources.append("env presence probe (values never read)")
    return {"worker": m.id, "name": m.name, "state": state, "provider": provider or "local",
            "credential_present": cred, "catalog_availability": m.availability.value,
            "certification": m.certification.value,
            "execution_authority": execution_authority(flags),
            "authority_note": "liveness never grants authority — execution needs the three brakes (§0 #12/§119)",
            "live_jobs": len(live), "heartbeats": len(hb), "reasons": reasons, "sources": sources}


def normalize(*, manifests, heartbeats=None, jobs=None, auth=None, health=None, flags=None) -> dict:
    """§119 snapshot over every coding-worker manifest. Runner heartbeat rows that match no catalog worker
    are reported under ``runner_plane`` (never hidden, never attributed to a worker)."""
    workers = [normalize_worker(m, heartbeats=heartbeats, jobs=jobs, auth=auth, health=health, flags=flags)
               for m in (manifests or []) if getattr(m, "worker_profile", None) is not None]
    matched = {h.get("worker_id") for m in (manifests or []) if getattr(m, "worker_profile", None) is not None
               for h in _heartbeats_for(m.id, heartbeats or [])}
    unmatched = [h for h in (heartbeats or []) if h.get("worker_id") not in matched]
    counts = {s: sum(1 for w in workers if w["state"] == s) for s in STATES}
    return {"version": WORKER_HEALTH_VERSION, "workers": workers, "counts": counts,
            "execution_authority": execution_authority(flags),
            "runner_plane": [{"worker_id": h.get("worker_id"), "online": bool(h.get("online")),
                              "current_job": h.get("current_job")} for h in unmatched],
            "states": list(STATES)}


def router_health(snapshot: dict) -> dict:
    """§119 → §11: the ``health`` map ``CodingWorkerRouter.select`` already accepts, from a normalize()
    snapshot — only an OBSERVED-live worker is healthy; AUTH_BLOCKED / OFFLINE / DEGRADED / QUARANTINED
    are rejected by the router as unhealthy. Liveness feeds SELECTION, never authority."""
    return {w["worker"]: w["state"] in LIVE_STATES for w in (snapshot or {}).get("workers", [])}


def snapshot(*, heartbeats=None, jobs=None, auth=None, health=None, flags=None) -> dict:
    """Live §119 snapshot from the REAL sources (each fail-soft → empty; the env probe is real)."""
    from app.services.capability.seed import seed_registry
    manifests = seed_registry().list()
    if heartbeats is None:
        try:
            from app.services.holding.status import list_workers
            heartbeats = list_workers()
        except Exception:
            heartbeats = []
    if jobs is None:
        try:
            from app.services.holding.worker_jobs import list_jobs
            jobs = list_jobs(limit=200)
        except Exception:
            jobs = []
    if flags is None:
        try:
            from app.services.holding.self_model import _flags
            flags = _flags()
        except Exception:
            flags = {}
    return normalize(manifests=manifests, heartbeats=heartbeats, jobs=jobs, auth=auth, health=health, flags=flags)


if __name__ == "__main__":
    from app.services.holding.test_worker_health import run
    raise SystemExit(0 if run() else 1)
