"""KAI self-audit — introspect every subsystem + runtime into a health report.

  auditor.run_audit() → {summary, runtime, subsystems[], issues[]}
  SUBSYSTEMS — the declarative inventory (keep in sync as features ship)
"""
from app.services.audit.auditor import SUBSYSTEMS, run_audit  # noqa: F401

__all__ = ["SUBSYSTEMS", "run_audit"]
