from __future__ import annotations

from .models import BackupStatus, CategoryScore, Finding, Posture, SecurityScore

# ── OPERATOR-OWNED CONFIG ─────────────────────────────────────────────
# Weights encode YOUR risk appetite. Edit these. They must sum > 0.
_WEIGHTS = {
    "Authentication": 1.0,
    "Encryption / secrets-at-rest": 1.0,
    "Backups": 1.0,
    "API Security": 0.8,
    "Agent Security": 1.0,
    "Infrastructure / Vulns": 1.0,
}
# Penalty per finding severity (points subtracted from the 100 baseline).
_PENALTY = {"critical": 45, "high": 25, "medium": 10, "low": 3, "info": 0}
# Backup freshness: snapshot older than this many seconds is stale.
_BACKUP_STALE_S = 36 * 3600
# ──────────────────────────────────────────────────────────────────────


def _category_weights() -> dict[str, float]:
    return dict(_WEIGHTS)


def _penalize(base: int, findings: list[Finding]) -> int:
    score = base
    for f in findings:
        score -= _PENALTY.get(f.severity, 0)
    return max(0, min(100, score))


def compute_score(
    findings: list[Finding],
    posture: Posture,
    backup: BackupStatus,
    *,
    secrets_scanned: bool,
    vulns_scanned: bool,
) -> SecurityScore:
    secrets = [f for f in findings if f.category == "secret"]
    vulns = [f for f in findings if f.category == "vuln"]
    cats: list[CategoryScore] = []

    # Authentication — static token today; MFA/user-table raise it (Phase 2)
    auth = 30
    if posture.mfa_enabled:
        auth += 40
    if posture.user_table_present:
        auth += 20
    cats.append(CategoryScore(name="Authentication", score=min(100, auth),
                              detail="static admin token; no MFA" if not posture.mfa_enabled else "MFA on"))

    # Encryption / secrets-at-rest — vault good, plaintext files + secret findings bad
    if not secrets_scanned and not posture.plaintext_secret_files:
        enc = None
        enc_detail = "not scanned"
    else:
        enc_base = 100 - 20 * len(posture.plaintext_secret_files)
        enc = _penalize(max(0, enc_base), secrets)
        enc_detail = f"{len(posture.plaintext_secret_files)} plaintext secret file(s), {len(secrets)} finding(s)"
    cats.append(CategoryScore(name="Encryption / secrets-at-rest", score=enc, detail=enc_detail))

    # Backups — real freshness
    if not backup.configured:
        cats.append(CategoryScore(name="Backups", score=0, detail="no restic repo configured"))
    elif backup.last_snapshot_age_s is None:
        cats.append(CategoryScore(name="Backups", score=20, detail="configured but no snapshot yet"))
    else:
        b = 100
        if backup.check_ok is False:
            b -= 50
        if backup.last_snapshot_age_s > _BACKUP_STALE_S:
            b -= 40
        cats.append(CategoryScore(name="Backups", score=max(0, b),
                                  detail=f"age={backup.last_snapshot_age_s}s check_ok={backup.check_ok}"))

    # API Security — HTTPS via Railway + bearer tiers; rate-limit unknown unless asserted
    api = 80
    if posture.rate_limiting_present is True:
        api = 95
    elif posture.rate_limiting_present is False:
        api = 65
    cats.append(CategoryScore(name="API Security", score=api,
                              detail="HTTPS+bearer tiers; rate-limit "
                                     + {True: "on", False: "MISSING", None: "unknown"}[posture.rate_limiting_present]))

    # Agent Security — governance is KAI's strength
    agent = 90 if posture.governance_ok else 40
    cats.append(CategoryScore(name="Agent Security", score=agent,
                              detail="scopes+@audited+kill-switches" if posture.governance_ok else "governance degraded"))

    # Infrastructure / Vulns
    if not vulns_scanned:
        cats.append(CategoryScore(name="Infrastructure / Vulns", score=None, detail="not scanned"))
    else:
        cats.append(CategoryScore(name="Infrastructure / Vulns", score=_penalize(100, vulns),
                                  detail=f"{len(vulns)} vuln finding(s)"))

    # Overall: weighted mean of KNOWN categories; cap below 100 if anything unknown
    weights = _category_weights()
    known = [(c, weights.get(c.name, 1.0)) for c in cats if c.score is not None]
    has_unknown = any(c.score is None for c in cats)
    if not known:
        overall = None
    else:
        total_w = sum(w for _, w in known) or 1.0
        overall = round(sum(c.score * w for c, w in known) / total_w)
        if has_unknown:
            overall = min(overall, 95)
    return SecurityScore(overall=overall, categories=cats)
