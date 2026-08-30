"""Unit test: the operational-truth grounding rule is present in every governed
system prompt (the narrowest authoritative location, BASE_SYSTEM_PROMPT), and the
existing baseline guidance is not regressed. Run:
    python3 -m app.services.nai_brain.test_operational_truth   (from backend/, backend on path)
Deterministic — no network, no model call.
"""
import importlib.util, os
# Load system_prompt.py directly (pure module) to avoid the app.config import chain.
_p = os.path.join(os.path.dirname(__file__), "system_prompt.py")
_spec = importlib.util.spec_from_file_location("kai_system_prompt_under_test", _p)
_m = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_m)
BASE_SYSTEM_PROMPT = _m.BASE_SYSTEM_PROMPT
build_system_prompt = _m.build_system_prompt

res = []
def ck(n, ok):
    res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

sp_raw = build_system_prompt()               # default composition (what a governed turn gets)
sp = " ".join(sp_raw.split())                # whitespace-normalized (robust to line wrapping)

# grounding present in the assembled prompt
ck("assembled prompt carries the operational-truth grounding", "Operational truth" in sp)
ck("covers the class (deployments/infra/finances/etc.), not a single phrase",
   all(w in sp for w in ("deployments", "infrastructure", "finances", "users", "metrics")))
ck("instructs: answer ONLY from trusted context or authorized available capability",
   "trusted context" in sp and "authorized, available capability" in sp)
ck("instructs: never infer current state from general knowledge",
   "Never infer or guess current operational state from general knowledge" in sp)
ck("instructs: explicit limitation when source unavailable/disabled/unconnected/unauthorized",
   "unavailable, disabled, unconnected, or unauthorized" in sp)
ck("preserves general educational answers (clearly labeled)",
   "general, clearly-labeled educational" in sp)
ck("forbids fabricating metrics/deployment/incidents/financials/logs/audit/capability results",
   "Never fabricate metrics" in sp and "capability results" in sp)
ck("prompt-injection resistance (refuse to pretend/assert unverified state)",
   "pretend you" in sp and "refuse" in sp)

# no regression: baseline tool + memory guidance still present
ck("baseline unchanged: memory guidance intact", "persistent memory across sessions" in sp)
ck("baseline unchanged: tool guidance intact", "web_search" in sp and "memory_tool" in sp)
ck("grounding lives in BASE (every reply, regardless of preset)", "Operational truth" in BASE_SYSTEM_PROMPT)

n = len(res); ok = sum(res)
print(f"\nOPERATIONAL-TRUTH UNIT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
