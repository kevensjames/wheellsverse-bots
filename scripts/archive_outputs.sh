#!/usr/bin/env bash
# ============================================================================
# archive_outputs.sh
# ============================================================================
#
# PURPOSE
#   Archive stale (30-90 day inactive) subdirectories under outputs/ to free
#   disk space while preserving content. Based on outputs/ audit 2026-06-19
#   which identified ~198M (14% of 1.4G total) across 13 dirs as archivable.
#
# WHEN TO RUN
#   - After confirming a generation cycle has completed (avoid 05:00-09:00
#     peak generation hours to prevent file conflicts).
#   - When disk pressure on /Volumes/Wheellsverse warrants reclaim.
#   - Quarterly as a maintenance pass.
#   - NEVER during active KDP/audio/book generation runs.
#
# HOW TO UNDO
#   Archived files are moved (not deleted) to:
#     /Volumes/Wheellsverse/archive/outputs-YYYYMMDD/
#   To restore a directory:
#     rsync -av /Volumes/Wheellsverse/archive/outputs-YYYYMMDD/<dir>/ \
#               /Volumes/Wheellsverse/wheellsverse-bots/outputs/<dir>/
#   The full run log lives at:
#     /Volumes/Wheellsverse/wheellsverse-bots/scripts/logs/archive_outputs_<TS>.log
#   No file is deleted by this script — rsync --remove-source-files only
#   removes the SOURCE after the destination copy is verified by rsync's
#   internal checksum. Empty source directories are removed last via find.
#
# SAFETY
#   - DEFAULTS TO --dry-run. You MUST pass --execute to move anything.
#   - Refuses to touch any subdir modified within the last 7 days.
#   - Refuses to run if destination is not under /Volumes/Wheellsverse.
#   - Requires rsync to be installed.
#
# USAGE
#   ./archive_outputs.sh                       # dry-run, default destination
#   ./archive_outputs.sh --execute             # actually move
#   ./archive_outputs.sh --destination /path   # custom destination (must be
#                                                under /Volumes/Wheellsverse)
# ============================================================================

set -euo pipefail

# ---------- config ----------------------------------------------------------
OUTPUTS_DIR="/Volumes/Wheellsverse/wheellsverse-bots/outputs"
DEFAULT_DEST_ROOT="/Volumes/Wheellsverse/archive"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
TS="$(date +%Y%m%d_%H%M%S)"
TODAY="$(date +%Y%m%d)"
LOG_FILE="${LOG_DIR}/archive_outputs_${TS}.log"
SAFETY_FRESH_DAYS=7
ALLOWED_DEST_PREFIX="/Volumes/Wheellsverse"

# ---------- targets ---------------------------------------------------------
# Confirmed archival targets from discovery audit 2026-06-19 (30-90d stale).
# Order: largest first so disk pressure is relieved early on partial runs.
ARCHIVE_TARGETS=(
  "covers"          # 94M,  last modified 54d ago — design assets
  "videos"          # 78M,  last modified 42d ago — video files
  "screenshots"     # 36M,  last modified 80d ago — sparse screenshots
  "specialized"     # 13M,  last modified 48d ago — project outputs
  "social_images"   # 8.3M, last modified 42d ago — image assets
  "sales"           # 1.9M, last modified 56d ago — sales collateral
  "business"        # 1.7M, last modified 74d ago — business outputs
  "seo_autopilot"   # 740K, last modified 57d ago — SEO outputs
  "ecommerce"       # 496K, last modified 74d ago — e-commerce data
  "aeo"             # 48K,  last modified 79d ago — minimal
  "campaigns"       # 40K,  last modified 70d ago — minimal
  "prompt_intel"    # 12K,  last modified 80d ago — minimal
  "narai"           # 0B,   empty
  "core"            # 0B,   empty
)

# ---------- CONFIRM-FIRST (AMBIGUOUS) ---------------------------------------
# The following subdirs were flagged as in-progress / actively regenerating in
# the audit (modified today or within last 7 days). They are NOT archived by
# this script. If a future audit clears them, uncomment and move into
# ARCHIVE_TARGETS above. Do NOT enable without re-running discovery.
#
# AMBIGUOUS_TARGETS=(
#   "audio"            # 737M  — IN-PROGRESS, daily generation
#   "books"            # 308M  — IN-PROGRESS, daily generation
#   "customer_support" # 62M   — IN-PROGRESS, active
#   "content"          # 25M   — IN-PROGRESS, continuous output
#   "assistant"        # 23M   — IN-PROGRESS, daily use
#   "marketing"        # 14M   — IN-PROGRESS
#   "social_media"     # 13M   — IN-PROGRESS
#   "writing"          # 7.6M  — IN-PROGRESS
#   "published"        # 4.1M  — SHIPPED but live blog; check symlinks first
#   "repurposed"       # 1.9M  — daily repurposing
# )

# ---------- arg parsing -----------------------------------------------------
MODE="dry-run"
DEST_ROOT="${DEFAULT_DEST_ROOT}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)     MODE="dry-run"; shift ;;
    --execute)     MODE="execute"; shift ;;
    --destination) DEST_ROOT="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,60p' "$0"
      exit 0
      ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      echo "Try: $0 --help" >&2
      exit 2
      ;;
  esac
done

DEST_DIR="${DEST_ROOT}/outputs-${TODAY}"

# ---------- preflight -------------------------------------------------------
mkdir -p "${LOG_DIR}"

log() {
  local msg="$1"
  echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] ${msg}" | tee -a "${LOG_FILE}"
}

die() {
  log "FATAL: $1"
  exit 1
}

command -v rsync >/dev/null 2>&1 || die "rsync is not installed"

[[ -d "${OUTPUTS_DIR}" ]] || die "outputs dir not found: ${OUTPUTS_DIR}"

case "${DEST_ROOT}" in
  "${ALLOWED_DEST_PREFIX}"*) : ;;
  *) die "destination must be under ${ALLOWED_DEST_PREFIX} (got: ${DEST_ROOT})" ;;
esac

log "================================================================"
log "archive_outputs.sh  mode=${MODE}"
log "  source:      ${OUTPUTS_DIR}"
log "  destination: ${DEST_DIR}"
log "  log file:    ${LOG_FILE}"
log "  safety:      refuse subdirs modified within ${SAFETY_FRESH_DAYS} days"
log "================================================================"

# ---------- before snapshot -------------------------------------------------
log ""
log "DISK USAGE BEFORE:"
du -sh "${OUTPUTS_DIR}" 2>/dev/null | tee -a "${LOG_FILE}" || true
df -h "${OUTPUTS_DIR}" 2>/dev/null | tee -a "${LOG_FILE}" || true

# ---------- per-target loop -------------------------------------------------
ARCHIVED_COUNT=0
SKIPPED_COUNT=0
MISSING_COUNT=0

for target in "${ARCHIVE_TARGETS[@]}"; do
  src="${OUTPUTS_DIR}/${target}"
  dst="${DEST_DIR}/${target}"

  log ""
  log "----------------------------------------------------------------"
  log "TARGET: ${target}"

  if [[ ! -e "${src}" ]]; then
    log "  SKIP: source does not exist (${src})"
    MISSING_COUNT=$((MISSING_COUNT + 1))
    continue
  fi

  # safety: refuse if anything inside was modified within SAFETY_FRESH_DAYS
  recent="$(find "${src}" -type f -mtime -${SAFETY_FRESH_DAYS} -print -quit 2>/dev/null || true)"
  if [[ -n "${recent}" ]]; then
    log "  SKIP: contains files modified within ${SAFETY_FRESH_DAYS} days"
    log "        example: ${recent}"
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    continue
  fi

  size="$(du -sh "${src}" 2>/dev/null | awk '{print $1}')"
  fcount="$(find "${src}" -type f 2>/dev/null | wc -l | tr -d ' ')"
  log "  size:  ${size}"
  log "  files: ${fcount}"

  if [[ "${MODE}" == "dry-run" ]]; then
    log "  DRY-RUN: would rsync ${src}/  ->  ${dst}/"
    log "  DRY-RUN: would remove emptied source: ${src}"
    rsync -an --stats "${src}/" "${dst}/" 2>&1 \
      | sed -n '/Number of files:/,/Total bytes received:/p' \
      | sed 's/^/    /' \
      | tee -a "${LOG_FILE}" || true
  else
    mkdir -p "${dst}"
    log "  EXEC: rsync -a --remove-source-files ${src}/ -> ${dst}/"
    rsync -a --remove-source-files \
          --log-file="${LOG_FILE}" \
          "${src}/" "${dst}/"
    # remove now-empty source directory tree
    find "${src}" -type d -empty -delete 2>/dev/null || true
    if [[ -d "${src}" ]]; then
      log "  WARN: source dir not empty after rsync — left in place: ${src}"
    else
      log "  OK: source removed"
    fi
    ARCHIVED_COUNT=$((ARCHIVED_COUNT + 1))
  fi
done

# ---------- after snapshot --------------------------------------------------
log ""
log "================================================================"
log "DISK USAGE AFTER:"
du -sh "${OUTPUTS_DIR}" 2>/dev/null | tee -a "${LOG_FILE}" || true
df -h "${OUTPUTS_DIR}" 2>/dev/null | tee -a "${LOG_FILE}" || true

if [[ "${MODE}" == "execute" && -d "${DEST_DIR}" ]]; then
  log ""
  log "ARCHIVE DESTINATION:"
  du -sh "${DEST_DIR}" 2>/dev/null | tee -a "${LOG_FILE}" || true
fi

log ""
log "SUMMARY  mode=${MODE}"
log "  archived: ${ARCHIVED_COUNT}"
log "  skipped:  ${SKIPPED_COUNT} (fresh / safety)"
log "  missing:  ${MISSING_COUNT}"
log "  log:      ${LOG_FILE}"

if [[ "${MODE}" == "dry-run" ]]; then
  log ""
  log "This was a DRY RUN. Re-run with --execute to actually archive."
fi
