#!/usr/bin/env python3
"""
bots/core/bug_hunter/scanner.py
─────────────────────────────────────────────────────────────────────────────
Static source scanner. Walks .py files and returns raw findings for the
detector to classify.
─────────────────────────────────────────────────────────────────────────────
"""

import ast
import re
import tokenize
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).parent.parent.parent.parent


@dataclass
class RawFinding:
    file: str
    line: int
    col: int
    kind: str          # e.g. "bare_except", "hardcoded_secret", "unbounded_list"
    snippet: str       # the offending source line
    context: str = ""  # extra info


class Scanner:
    """
    Scans Python source files for common bug patterns.
    Returns a list of RawFinding objects.
    """

    # Patterns that suggest hardcoded secrets (key=literal string with entropy)
    _SECRET_RE = re.compile(
        r'(api_key|secret|password|token|passwd)\s*=\s*["\']([^"\']{8,})["\']',
        re.IGNORECASE,
    )
    # Bare except: / except Exception: pass
    _BARE_EXCEPT_RE = re.compile(r"^\s*except\s*(?:Exception\s*)?:\s*pass\s*$")
    # except: (bare, no type)
    _TRULY_BARE_RE = re.compile(r"^\s*except\s*:\s*$")

    def scan_path(self, path: Path) -> List[RawFinding]:
        findings: List[RawFinding] = []
        for py_file in sorted(path.rglob("*.py")):
            try:
                findings.extend(self.scan_file(py_file))
            except Exception:
                pass
        return findings

    def scan_file(self, path: Path) -> List[RawFinding]:
        findings: List[RawFinding] = []
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return findings

        rel = str(path.relative_to(ROOT))
        lines = source.splitlines()

        findings.extend(self._check_secrets(rel, lines))
        findings.extend(self._check_bare_excepts(rel, lines))
        findings.extend(self._check_ast(rel, source, lines))

        return findings

    def _check_secrets(self, rel: str, lines: List[str]) -> List[RawFinding]:
        findings = []
        for i, line in enumerate(lines, 1):
            m = self._SECRET_RE.search(line)
            if m:
                value = m.group(2)
                # Skip obvious placeholders
                if any(p in value.lower() for p in ("your", "xxx", "placeholder", "example", "changeme", "<")):
                    continue
                findings.append(RawFinding(
                    file=rel, line=i, col=m.start(),
                    kind="hardcoded_secret",
                    snippet=line.strip()[:120],
                    context=f"key='{m.group(1)}'"
                ))
        return findings

    def _check_bare_excepts(self, rel: str, lines: List[str]) -> List[RawFinding]:
        findings = []
        for i, line in enumerate(lines, 1):
            if self._TRULY_BARE_RE.match(line):
                findings.append(RawFinding(
                    file=rel, line=i, col=0,
                    kind="bare_except",
                    snippet=line.strip(),
                    context="bare 'except:' catches BaseException including KeyboardInterrupt"
                ))
            elif self._BARE_EXCEPT_RE.match(line):
                findings.append(RawFinding(
                    file=rel, line=i, col=0,
                    kind="silent_except_pass",
                    snippet=line.strip(),
                    context="exception silently swallowed"
                ))
        return findings

    def _check_ast(self, rel: str, source: str, lines: List[str]) -> List[RawFinding]:
        findings = []
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            findings.append(RawFinding(
                file=rel, line=e.lineno or 0, col=e.offset or 0,
                kind="syntax_error",
                snippet=str(e),
                context="file has a syntax error and cannot be imported"
            ))
            return findings

        for node in ast.walk(tree):
            # Detect list used as default mutable argument
            if isinstance(node, ast.FunctionDef):
                for default in node.args.defaults + node.args.kw_defaults:
                    if default and isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        line = node.lineno
                        findings.append(RawFinding(
                            file=rel, line=line, col=0,
                            kind="mutable_default_arg",
                            snippet=lines[line - 1].strip()[:120] if line <= len(lines) else "",
                            context=f"function '{node.name}' has mutable default argument"
                        ))
                        break

            # Detect os.system() calls (prefer subprocess)
            if (isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Attribute) and
                    node.func.attr == "system" and
                    isinstance(node.func.value, ast.Name) and
                    node.func.value.id == "os"):
                line = node.lineno
                findings.append(RawFinding(
                    file=rel, line=line, col=0,
                    kind="os_system_call",
                    snippet=lines[line - 1].strip()[:120] if line <= len(lines) else "",
                    context="os.system() is a shell injection risk; use subprocess"
                ))

            # Detect print() used as logging (in non-CLI files)
            if (isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and
                    node.func.id == "print" and
                    "test" not in rel and "cli" not in rel):
                line = node.lineno
                findings.append(RawFinding(
                    file=rel, line=line, col=0,
                    kind="print_as_logging",
                    snippet=lines[line - 1].strip()[:120] if line <= len(lines) else "",
                    context="use logger.* instead of print() for structured logging"
                ))

            # Detect unbounded list append in a loop (potential memory leak)
            if isinstance(node, (ast.For, ast.While)):
                for child in ast.walk(node):
                    if (isinstance(child, ast.Call) and
                            isinstance(child.func, ast.Attribute) and
                            child.func.attr == "append"):
                        line = node.lineno
                        findings.append(RawFinding(
                            file=rel, line=line, col=0,
                            kind="unbounded_loop_append",
                            snippet=lines[line - 1].strip()[:120] if line <= len(lines) else "",
                            context="list.append() inside loop — verify list is bounded or cleared"
                        ))
                        break

        return findings
