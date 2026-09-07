"""ONE money-state resolver (CEO truth gate, Phase 0).

THE DEFECT THIS REMOVES. The dashboard reported `money_mode: MOCK` on production while `MONEY_MODE`
is **not declared in App B's Settings at all**. The value came from `getattr(settings, "MONEY_MODE",
"MOCK")` — a default, presented as observed runtime state. "MOCK" and "I have no configured value" are
different facts, and the reader could not tell them apart.

It also collapsed four genuinely separate questions into one word:

    holding authority      may KAI take financial actions at all?
    provider mode          is a given payment provider in sandbox or live?
    environment            which environment is this?
    integration presence   is a payment integration actually wired and reachable?

A single `money_mode` cannot answer those. A product can be in Stripe *test* mode while the holding
company's financial authority is *off*, in *production*, with *no* integration configured. Reporting
one "MOCK" for that state is not a summary, it is a loss of four facts.

Absent means UNAVAILABLE. No reader may substitute a default and present it as runtime state.

Pure. No I/O. Plain python3 self-test.
"""
from __future__ import annotations

UNAVAILABLE = "UNAVAILABLE"

# Holding-level authority for financial actions.
AUTHORITY_OFF = "FINANCIAL_AUTHORITY_OFF"
AUTHORITY_ON = "FINANCIAL_AUTHORITY_ON"

# Provider-level mode, per integration.
MODE_SANDBOX = "SANDBOX"
MODE_LIVE = "LIVE"

# Integration presence.
INTEGRATION_ABSENT = "NOT_CONFIGURED"
INTEGRATION_CONFIGURED = "CONFIGURED"

_SENTINEL = object()

_TRUTHY = ("1", "true", "yes", "on", "live", "production")
_SANDBOXY = ("mock", "test", "sandbox", "0", "false", "off")


def _declared(settings, name):
    """The declared value, or the sentinel. getattr with a default is exactly the bug this avoids."""
    v = getattr(settings, name, _SENTINEL)
    return v


def resolve(settings, *, providers=("stripe", "dwolla")) -> dict:
    """Four separately-sourced answers, each carrying where it came from.

    Every field reports its own `source`, so a reader can distinguish an observed value from an
    absent one without inspecting the resolver."""
    out: dict = {}

    # 1. Environment — the least ambiguous fact available.
    env = _declared(settings, "APP_ENV")
    out["environment"] = {
        "value": (str(env).strip().lower() if env is not _SENTINEL and env else UNAVAILABLE),
        "source": "settings.APP_ENV" if env is not _SENTINEL and env else "not declared",
    }

    # 2. Holding authority for financial actions. Absent is UNAVAILABLE, never assumed off OR on.
    #    "We do not know whether financial authority is granted" is a state an operator must see.
    raw_mode = _declared(settings, "MONEY_MODE")
    if raw_mode is _SENTINEL or raw_mode in (None, ""):
        out["holding_financial_authority"] = {
            "value": UNAVAILABLE,
            "source": "MONEY_MODE is not declared in this app's Settings",
            "note": ("previously reported MOCK — that was a getattr() default presented as runtime "
                     "state, not an observed value"),
        }
        out["declared_money_mode"] = {"value": UNAVAILABLE, "source": "not declared"}
    else:
        m = str(raw_mode).strip().lower()
        authority = AUTHORITY_ON if m in _TRUTHY else AUTHORITY_OFF
        out["holding_financial_authority"] = {"value": authority, "source": "settings.MONEY_MODE"}
        out["declared_money_mode"] = {"value": str(raw_mode), "source": "settings.MONEY_MODE"}

    # 3 + 4. Per-provider mode and integration presence — sourced independently of the global.
    provs: dict = {}
    for name in providers:
        key_names = _PROVIDER_KEYS.get(name, ())
        configured = any(_declared(settings, k) not in (_SENTINEL, None, "") for k in key_names)
        env_name = f"{name.upper()}_ENV"
        raw_env = _declared(settings, env_name)
        if not configured:
            mode, src = UNAVAILABLE, f"no {name} credential configured"
        elif raw_env is _SENTINEL or raw_env in (None, ""):
            mode, src = UNAVAILABLE, f"{env_name} not declared"
        else:
            e = str(raw_env).strip().lower()
            mode = MODE_LIVE if e in _TRUTHY else (MODE_SANDBOX if e in _SANDBOXY else UNAVAILABLE)
            src = f"settings.{env_name}"
        provs[name] = {
            "integration": INTEGRATION_CONFIGURED if configured else INTEGRATION_ABSENT,
            "mode": mode,
            "source": src,
        }
    out["providers"] = provs

    # A single sentence that does NOT collapse the four facts.
    out["summary"] = _summary(out)
    return out


_PROVIDER_KEYS = {
    "stripe": ("STRIPE_SECRET_KEY", "STRIPE_API_KEY"),
    "dwolla": ("DWOLLA_KEY", "DWOLLA_SECRET"),
}


def _summary(o: dict) -> str:
    auth = o["holding_financial_authority"]["value"]
    live = [n for n, p in o["providers"].items() if p["mode"] == MODE_LIVE]
    configured = [n for n, p in o["providers"].items()
                  if p["integration"] == INTEGRATION_CONFIGURED]
    if auth == UNAVAILABLE:
        base = "Financial authority is UNAVAILABLE — not declared in this app, so it cannot be reported."
    elif auth == AUTHORITY_OFF:
        base = "KAI holds no financial authority."
    else:
        base = "KAI holds financial authority."
    if not configured:
        return base + " No payment integration is configured."
    if live:
        return base + f" LIVE provider(s): {', '.join(sorted(live))}."
    return base + f" Configured provider(s) in sandbox or unknown mode: {', '.join(sorted(configured))}."


# ── self-test ─────────────────────────────────────────────────────────────────────────────────────
_res: list = []


def ck(name, ok):
    _res.append((name, bool(ok)))


class _S:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def demo() -> None:
    # THE PRODUCTION SHAPE: APP_ENV declared, MONEY_MODE absent.
    prod = resolve(_S(APP_ENV="production"))
    ck("an UNDECLARED MONEY_MODE reports UNAVAILABLE, never a defaulted MOCK",
       prod["holding_financial_authority"]["value"] == UNAVAILABLE)
    ck("...and says WHY, naming the missing declaration",
       "not declared" in prod["holding_financial_authority"]["source"])
    ck("...and records that the old MOCK was a default, not an observation",
       "getattr" in prod["holding_financial_authority"]["note"])
    ck("environment resolves independently", prod["environment"]["value"] == "production")
    ck("no provider configured -> NOT_CONFIGURED, mode UNAVAILABLE",
       prod["providers"]["stripe"]["integration"] == INTEGRATION_ABSENT
       and prod["providers"]["stripe"]["mode"] == UNAVAILABLE)
    ck("the summary does not claim a money mode it cannot observe",
       "UNAVAILABLE" in prod["summary"] and "MOCK" not in prod["summary"])

    # The four facts are genuinely independent.
    mixed = resolve(_S(APP_ENV="production", MONEY_MODE="MOCK",
                       STRIPE_SECRET_KEY="sk_test_x", STRIPE_ENV="test"))
    ck("authority OFF can coexist with a CONFIGURED provider",
       mixed["holding_financial_authority"]["value"] == AUTHORITY_OFF
       and mixed["providers"]["stripe"]["integration"] == INTEGRATION_CONFIGURED)
    ck("...and the provider's own mode is reported separately",
       mixed["providers"]["stripe"]["mode"] == MODE_SANDBOX)
    ck("...in a production environment, all at once",
       mixed["environment"]["value"] == "production")

    live = resolve(_S(APP_ENV="production", MONEY_MODE="live",
                      STRIPE_SECRET_KEY="sk_live_x", STRIPE_ENV="production"))
    ck("a genuinely live provider reports LIVE", live["providers"]["stripe"]["mode"] == MODE_LIVE)
    ck("...and authority ON is reported as ON",
       live["holding_financial_authority"]["value"] == AUTHORITY_ON)
    ck("...and the summary names the live provider", "stripe" in live["summary"])

    # Configured but with no declared env is UNAVAILABLE, not assumed sandbox.
    amb = resolve(_S(APP_ENV="staging", MONEY_MODE="MOCK", STRIPE_SECRET_KEY="sk_x"))
    ck("configured provider with no declared env -> mode UNAVAILABLE, never assumed sandbox",
       amb["providers"]["stripe"]["mode"] == UNAVAILABLE
       and amb["providers"]["stripe"]["integration"] == INTEGRATION_CONFIGURED)

    # Nothing declared at all.
    empty = resolve(_S())
    ck("nothing declared -> every field UNAVAILABLE, none defaulted",
       empty["environment"]["value"] == UNAVAILABLE
       and empty["holding_financial_authority"]["value"] == UNAVAILABLE
       and all(p["mode"] == UNAVAILABLE for p in empty["providers"].values()))
    ck("every field carries its own source", all(
        "source" in empty[k] for k in ("environment", "holding_financial_authority")))

    bad = [n for n, ok in _res if not ok]
    for n in bad:
        print("  FAIL:", n)
    print(f"MONEY STATE TESTS: {len(_res) - len(bad)}/{len(_res)} — {'PASS' if not bad else 'FAIL'}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    demo()
