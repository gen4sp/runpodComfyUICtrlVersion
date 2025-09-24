#!/usr/bin/env bash
# shellcheck disable=SC1091
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$SCRIPT_DIR/lib/common.sh" ]; then . "$SCRIPT_DIR/lib/common.sh"; fi

usage() {
  cat <<'EOF'
Локальный запуск handler (без Docker): применить lock, проверить модели и вывести результат.

Usage:
  scripts/run_handler_local.sh --lock PATH --workflow PATH [--output base64|gcs] [--out-file PATH]
EOF
}

LOCK=""
WORKFLOW=""
OUTPUT=""
OUT_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock) LOCK="$2"; shift 2;;
    --workflow) WORKFLOW="$2"; shift 2;;
    --output) OUTPUT="$2"; shift 2;;
    --out-file) OUT_FILE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1;;
  esac
done

if [ -z "$LOCK" ]; then echo "--lock required" >&2; exit 1; fi
if [ -z "$WORKFLOW" ]; then echo "--workflow required" >&2; exit 1; fi

cd "$ROOT_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Build command arguments
ARGS=()
ARGS+=(--lock "$LOCK")
ARGS+=(--workflow "$WORKFLOW")
if [ -n "$OUTPUT" ]; then
  ARGS+=(--output "$OUTPUT")
fi
if [ -n "$OUT_FILE" ]; then
  ARGS+=(--out-file "$OUT_FILE")
fi

echo "Running: $PYTHON_BIN -m rp_handler.main ${ARGS[*]}"
"$PYTHON_BIN" -m rp_handler.main "${ARGS[@]}"


