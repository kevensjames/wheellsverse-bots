#!/usr/bin/env python3
"""
bots/core/bug_hunter/detector.py
─────────────────────────────────────────────────────────────────────────────
Classifies raw scanner findings into structured Bug objects with severity,
category, and suggested fix.
─────────────────────────────────────────────────────────────────────────────
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
from .scanner import RawFinding


SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


@dataclass
class Bug:
    id: str
    file: str
    line: int
    col: int
    severity: str       # CRITICAL / HIGH / MEDIUM / LOW / INFO
    category: str       # security / reliability / performance / style
    title: str
    description: str
    snippet: str
    fix_hint: str
    auto_fixable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "snippet": self.snippet,
            "fix_hint": self.fix_hint,
            "auto_fixable": self.auto_fixable,
        }


# Maps finding kind → (severity, category, title, fix_hint, auto_fixable)
_RULES: Dict[str, tuple] = {
    "hardcoded_secret": (
        "CRITICAL", "security",
        "Hardcoded credential in source",
        "Move secret to .env / os.getenv(); ensure .gitignore covers .env",
        False,
    ),
    "bare_except": (
        "HIGH", "reliability",
        "Bare except: catches BaseException",
        "Replace with 'except Exception as e:' and log the error",
        True,
    ),
    "silent_except_pass": (
        "MEDIUM", "reliability",
        "Silent exception swallow (except ... pass)",
        "Add 'logger.warning(...)' inside the except block",
        True,
    ),
    "syntax_error": (
        "CRITICAL", "reliability",
        "Syntax error — module cannot be imported",
        "Fix the syntax error reported in the snippet",
        False,
    ),
    "mutable_default_arg": (
        "HIGH", "reliability",
        "Mutable default argument",
        "Replace default [] / {} with None and initialise inside function body",
        False,
    ),
    "os_system_call": (
        "HIGH", "security",
        "os.system() shell injection risk",
        "Use subprocess.run([...], check=True) instead",
        False,
    ),
    "print_as_logging": (
        "LOW", "style",
        "print() used instead of logger",
        "Replace with logger.info() / logger.debug()",
        False,
    ),
    "unbounded_loop_append": (
        "MEDIUM", "performance",
        "Potentially unbounded list growth in loop",
        "Verify list is bounded; consider deque(maxlen=N) or periodically clearing",
        False,
    ),
}


class Detector:
    def __init__(self):
        self._counter = 0

    def classify(self, findings: List[RawFinding]) -> List[Bug]:
        bugs: List[Bug] = []
        for f in findings:
            rule = _RULES.get(f.kind)
            if rule is None:
                continue
            severity, category, title, fix_hint, auto_fixable = rule
            self._counter += 1
            bug_id = f"BH-{self._counter:04d}"
            bugs.append(Bug(
                id=bug_id,
                file=f.file,
                line=f.line,
                col=f.col,
                severity=severity,
                category=category,
                title=title,
                description=f.context or title,
                snippet=f.snippet,
                fix_hint=fix_hint,
                auto_fixable=auto_fixable,
            ))
        # Sort by severity rank, then file, then line
        bugs.sort(key=lambda b: (SEVERITY_RANK.get(b.severity, 99), b.file, b.line))
        return bugs

    def summary(self, bugs: List[Bug]) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        for b in bugs:
            counts[b.severity] = counts.get(b.severity, 0) + 1
            by_category[b.category] = by_category.get(b.category, 0) + 1
        return {
            "total": len(bugs),
            "by_severity": counts,
            "by_category": by_category,
            "auto_fixable": sum(1 for b in bugs if b.auto_fixable),
        }
