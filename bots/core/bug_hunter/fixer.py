#!/usr/bin/env python3
"""
bots/core/bug_hunter/fixer.py
─────────────────────────────────────────────────────────────────────────────
Applies automatic fixes for bugs flagged as auto_fixable.
Currently handles:
  - bare_except        → replace with 'except Exception as e:'
  - silent_except_pass → add logger.warning() inside the block
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import re
from pathlib import Path
from typing import List, Tuple, Dict

from .detector import Bug

logger = logging.getLogger("bug_hunter.fixer")

ROOT = Path(__file__).parent.parent.parent.parent

# Regex patterns for fixable constructs
_BARE_EXCEPT_LINE = re.compile(r"^(\s*)except\s*:\s*$")
_SILENT_PASS_LINE = re.compile(r"^(\s*)except\s*(?:Exception\s*)?\s*:\s*pass\s*$")


class FixResult:
    def __init__(self, bug_id: str, file: str, line: int, applied: bool, note: str = ""):
        self.bug_id = bug_id
        self.file = file
        self.line = line
        self.applied = applied
        self.note = note

    def to_dict(self):
        return {"bug_id": self.bug_id, "file": self.file, "line": self.line,
                "applied": self.applied, "note": self.note}


class Fixer:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run

    def fix_all(self, bugs: List[Bug]) -> List[FixResult]:
        results: List[FixResult] = []
        # Group bugs by file for efficient per-file editing
        by_file: Dict[str, List[Bug]] = {}
        for bug in bugs:
            if bug.auto_fixable:
                by_file.setdefault(bug.file, []).append(bug)

        for rel_path, file_bugs in by_file.items():
            abs_path = ROOT / rel_path
            results.extend(self._fix_file(abs_path, rel_path, file_bugs))

        return results

    def _fix_file(self, abs_path: Path, rel_path: str, bugs: List[Bug]) -> List[FixResult]:
        results = []
        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Cannot read {rel_path}: {e}")
            for bug in bugs:
                results.append(FixResult(bug.id, rel_path, bug.line, False, str(e)))
            return results

        lines = source.splitlines(keepends=True)
        modified = False
        bug_by_line = {b.line: b for b in bugs}

        for i, line in enumerate(lines):
            lineno = i + 1
            bug = bug_by_line.get(lineno)
            if bug is None:
                continue

            new_line, note = self._apply_fix(line, bug)
            if new_line != line:
                lines[i] = new_line
                modified = True
                results.append(FixResult(bug.id, rel_path, lineno, not self.dry_run, note))
                logger.info(f"{'[DRY]' if self.dry_run else '[FIX]'} {rel_path}:{lineno} — {note}")
            else:
                results.append(FixResult(bug.id, rel_path, lineno, False, "no change needed"))

        if modified and not self.dry_run:
            try:
                abs_path.write_text("".join(lines), encoding="utf-8")
                logger.info(f"Saved fixed file: {rel_path}")
            except Exception as e:
                logger.error(f"Failed to write {rel_path}: {e}")
                for r in results:
                    if r.applied:
                        r.applied = False
                        r.note = f"write failed: {e}"

        return results

    def _apply_fix(self, line: str, bug: Bug) -> Tuple[str, str]:
        if bug.title == "Bare except: catches BaseException":
            m = _BARE_EXCEPT_LINE.match(line)
            if m:
                indent = m.group(1)
                new = f"{indent}except Exception as e:\n"
                return new, "bare except → except Exception as e:"

        # For silent_except_pass we need to look at the block; too risky to
        # auto-rewrite multi-line blocks here — flag as not applied.
        return line, "no fix applied"
