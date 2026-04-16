"""
core/security_scanner.py
─────────────────────────────────────────────────────────────────────────────
Defensive Security Scanner — educational / protective use only.

Scans files and directories for:
- Known malware file hashes (SHA-256) from a local DB
- Suspicious code patterns: obfuscated payloads, reverse shell patterns,
  credential harvesting, privilege escalation tricks
- Executable files with suspicious attributes
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("narai.security")

# ─── Known-bad SHA-256 hashes ─────────────────────────────────────────────────
# Minimal built-in list (EICAR test file + common test hashes).
# Extend by loading data/malware_hashes.json if it exists.

_BUILTIN_HASHES: set[str] = {
    # EICAR test file (safe, used to test AV)
    "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f",
    # EICAR COM variant
    "cf8bd9dfddff007f75adf4273cf74046f4c6a18a2ae58f64b52bce6e6ba2b8b3",
}

_HASH_DB_PATH = Path("data/malware_hashes.json")


def _load_hash_db() -> set[str]:
    hashes = set(_BUILTIN_HASHES)
    if _HASH_DB_PATH.exists():
        try:
            extra = json.loads(_HASH_DB_PATH.read_text())
            if isinstance(extra, list):
                hashes.update(h.lower() for h in extra if isinstance(h, str))
        except Exception as e:
            log.warning("Could not load malware_hashes.json: %s", e)
    return hashes


# ─── Suspicious pattern signatures ───────────────────────────────────────────

_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, severity, description)
    (r"eval\s*\(\s*base64_decode",   "HIGH",   "PHP eval+base64 obfuscation"),
    (r"exec\s*\(\s*base64_decode",   "HIGH",   "PHP exec+base64 obfuscation"),
    (r"__import__\s*\(\s*['\"]os['\"].*system", "HIGH", "Python dynamic OS exec"),
    (r"subprocess\.(?:call|run|Popen).*shell\s*=\s*True", "MEDIUM", "Shell injection risk"),
    (r"os\.system\s*\(\s*['\"]nc\s", "HIGH",   "Netcat reverse shell pattern"),
    (r"bash\s+-i\s+>&\s*/dev/tcp",   "HIGH",   "Bash reverse shell"),
    (r"python.*-c.*import\s+socket", "HIGH",   "Python reverse shell pattern"),
    (r"curl\s+.*\|\s*bash",          "HIGH",   "Curl-pipe-bash execution"),
    (r"wget\s+.*-O\s*-\s*\|\s*sh",  "HIGH",   "Wget-pipe-sh execution"),
    (r"chmod\s+[0-9]*7[0-9]*\s+/",  "MEDIUM", "World-writable permission set on /"),
    (r"sudo\s+chmod\s+777",          "MEDIUM", "Sudo chmod 777"),
    (r"DROP\s+TABLE\s+",             "MEDIUM", "SQL DROP TABLE statement"),
    (r"rm\s+-rf\s+/",               "HIGH",   "Recursive delete from root"),
    (r"dd\s+if=.*of=/dev/",         "HIGH",   "Direct disk write via dd"),
    (r"mkfs\.",                      "HIGH",   "Disk format command"),
    (r"(?:password|passwd|secret|api_key)\s*=\s*['\"][^'\"]{8,}['\"]", "LOW", "Hardcoded credential candidate"),
    (r"(?:AKIA|ASIA|AROA)[A-Z0-9]{16}", "MEDIUM", "AWS access key pattern"),
    (r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----", "MEDIUM", "Private key in file"),
]

_COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE | re.MULTILINE), sev, desc)
                       for p, sev, desc in _PATTERNS]

# Extensions we will read as text for pattern scanning
_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".php", ".sh", ".bash", ".rb", ".pl",
    ".html", ".htm", ".css", ".json", ".yml", ".yaml", ".toml",
    ".txt", ".md", ".env", ".conf", ".cfg", ".ini", ".sql",
}

# Extensions that are inherently executable / suspicious if unexpected
_EXEC_EXTENSIONS = {".exe", ".dll", ".so", ".elf", ".bin", ".bat", ".cmd", ".vbs", ".ps1"}

# Max file size for content scanning (5 MB)
_MAX_SCAN_SIZE = 5 * 1024 * 1024


# ─── File scanning ────────────────────────────────────────────────────────────

def scan_file(path: str) -> dict:
    """
    Scan a single file for threats.
    Returns:
        {
          "path": str,
          "clean": bool,
          "findings": [{"type": str, "severity": str, "detail": str}],
          "sha256": str,
          "size": int,
          "scanned_at": str (ISO),
        }
    """
    target = Path(path).resolve()
    result: dict = {
        "path": str(target),
        "clean": True,
        "findings": [],
        "sha256": "",
        "size": 0,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }

    if not target.exists():
        result["findings"].append({"type": "error", "severity": "INFO", "detail": "File not found"})
        return result

    if not target.is_file():
        result["findings"].append({"type": "error", "severity": "INFO", "detail": "Not a regular file"})
        return result

    try:
        fstat = target.stat()
        result["size"] = fstat.st_size

        # 1. Hash check
        sha256 = _hash_file(target)
        result["sha256"] = sha256
        bad_hashes = _load_hash_db()
        if sha256 in bad_hashes:
            result["findings"].append({
                "type": "known_malware",
                "severity": "CRITICAL",
                "detail": f"SHA-256 matches known malware signature: {sha256[:16]}…",
            })

        # 2. Suspicious executable permissions on non-exe files
        suffix = target.suffix.lower()
        if suffix not in _EXEC_EXTENSIONS:
            mode = fstat.st_mode
            if bool(mode & stat.S_IXOTH):  # world-executable
                result["findings"].append({
                    "type": "permissions",
                    "severity": "LOW",
                    "detail": "File is world-executable but not an expected binary type",
                })

        # 3. Pattern scan (text files only, size limit)
        if suffix in _TEXT_EXTENSIONS and fstat.st_size <= _MAX_SCAN_SIZE:
            try:
                content = target.read_text(errors="replace")
                _pattern_scan(content, result["findings"])
            except Exception as e:
                log.debug("Could not read %s for pattern scan: %s", target, e)

    except PermissionError:
        result["findings"].append({"type": "error", "severity": "INFO", "detail": "Permission denied"})
    except Exception as e:
        result["findings"].append({"type": "error", "severity": "INFO", "detail": str(e)})

    result["clean"] = not any(f["severity"] in ("CRITICAL", "HIGH", "MEDIUM")
                               for f in result["findings"])
    return result


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _strip_definition_lines(content: str) -> str:
    """
    Remove lines that are just string/regex literal definitions (e.g. inside a
    patterns list like _PATTERNS) so a security scanner doesn't flag itself.
    These look like:  (r"...", "HIGH", "description"),
    """
    cleaned = []
    for line in content.splitlines():
        stripped = line.strip()
        # Skip lines that are just raw-string tuples used to define patterns
        if stripped.startswith('(r"') or stripped.startswith("(r'"):
            continue
        # Skip pure comment lines
        if stripped.startswith('#'):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _pattern_scan(content: str, findings: list) -> None:
    cleaned = _strip_definition_lines(content)
    for pattern, severity, desc in _COMPILED_PATTERNS:
        m = pattern.search(cleaned)
        if m:
            snippet = cleaned[max(0, m.start()-20):m.end()+20].replace("\n", " ").strip()
            findings.append({
                "type": "pattern",
                "severity": severity,
                "detail": f"{desc} — …{snippet[:120]}…",
            })


# ─── Directory scanning ───────────────────────────────────────────────────────

def scan_directory(
    path: str,
    max_files: int = 500,
    skip_hidden: bool = True,
) -> dict:
    """
    Recursively scan a directory.
    Returns:
        {
          "path": str,
          "files_scanned": int,
          "threats_found": int,
          "findings": [file_result, ...],   # only files with findings
          "clean": bool,
          "scanned_at": str,
        }
    """
    target = Path(path).resolve()
    summary: dict = {
        "path": str(target),
        "files_scanned": 0,
        "threats_found": 0,
        "findings": [],
        "clean": True,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }

    if not target.exists():
        summary["findings"].append({"path": str(target), "error": "Path not found"})
        return summary
    if not target.is_dir():
        # Single file
        result = scan_file(path)
        summary["files_scanned"] = 1
        if not result["clean"]:
            summary["findings"].append(result)
            summary["threats_found"] = 1
            summary["clean"] = False
        return summary

    count = 0
    for entry in target.rglob("*"):
        if count >= max_files:
            break
        if skip_hidden and any(part.startswith(".") for part in entry.parts):
            continue
        if not entry.is_file():
            continue
        count += 1
        result = scan_file(str(entry))
        if not result["clean"]:
            summary["findings"].append(result)
            summary["threats_found"] += 1

    summary["files_scanned"] = count
    summary["clean"] = summary["threats_found"] == 0
    return summary
