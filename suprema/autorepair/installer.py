"""launchd installer for daily autorepair runs on macOS.

Creates ~/Library/LaunchAgents/com.suprema.autorepair.plist that runs:
    /opt/homebrew/bin/python3 -m suprema.autorepair.cli fix --commit --notify

…at 06:00 local time every day. Logs go under the autorepair logs dir."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PLIST_LABEL = "com.suprema.autorepair"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
SUPREMA_ROOT = Path(__file__).resolve().parent.parent.parent  # /Volumes/Wheellsverse
LOG_DIR = Path(__file__).resolve().parent / "logs"


def _python_bin() -> str:
    return (
        shutil.which("python3")
        or "/opt/homebrew/bin/python3"
    )


def _plist_xml() -> str:
    py = _python_bin()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{py}</string>
        <string>-m</string>
        <string>suprema.autorepair.cli</string>
        <string>fix</string>
        <string>--commit</string>
        <string>--notify</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{SUPREMA_ROOT}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{SUPREMA_ROOT}</string>
        <key>SUPREMA_STDOUT</key>
        <string>0</string>
    </dict>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>{LOG_DIR / 'launchd.out'}</string>

    <key>StandardErrorPath</key>
    <string>{LOG_DIR / 'launchd.err'}</string>
</dict>
</plist>
"""


def install() -> int:
    LOG_DIR.mkdir(exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_plist_xml())

    # Reload into launchd
    try:
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)],
                       capture_output=True, text=True, timeout=10)
        r = subprocess.run(["launchctl", "load", str(PLIST_PATH)],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            print(f"launchctl load returned {r.returncode}: {r.stderr.strip()}")
            return 1
    except FileNotFoundError:
        print("launchctl not found — this installer is macOS-only.")
        return 1

    print(f"✓ installed: {PLIST_PATH}")
    print(f"  runs daily at 06:00 local")
    print(f"  logs:  {LOG_DIR}/launchd.{{out,err}}")
    print(f"  unload: launchctl unload {PLIST_PATH}")
    return 0
