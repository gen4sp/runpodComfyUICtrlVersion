#!/usr/bin/env bash
# shellcheck disable=SC1091
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$SCRIPT_DIR/lib/common.sh" ]; then . "$SCRIPT_DIR/lib/common.sh"; fi

usage() {
  cat <<'EOF'
Локальный запуск handler (без Docker): резолв/реалайз версии и запуск workflow.

Usage:
  scripts/run_handler_local.sh (--version-id ID | --spec PATH) --workflow PATH [--output base64|gcs] [--out-file PATH]
EOF
}

VERSION_ID=""
SPEC=""
WORKFLOW=""
OUTPUT=""
OUT_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version-id) VERSION_ID="$2"; shift 2;;
    --spec) SPEC="$2"; shift 2;;
    --workflow) WORKFLOW="$2"; shift 2;;
    --output) OUTPUT="$2"; shift 2;;
    --out-file) OUT_FILE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1;;
  esac
done

if [ -z "$WORKFLOW" ]; then echo "--workflow required" >&2; exit 1; fi
if [ -z "$VERSION_ID" ] && [ -z "$SPEC" ]; then echo "--version-id or --spec required" >&2; exit 1; fi

cd "$ROOT_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Build command arguments
ARGS=()
if [ -n "$VERSION_ID" ]; then
  ARGS+=(--version-id "$VERSION_ID")
fi
if [ -n "$SPEC" ]; then
  ARGS+=(--spec "$SPEC")
fi
ARGS+=(--workflow "$WORKFLOW")
if [ -n "$OUTPUT" ]; then
  ARGS+=(--output "$OUTPUT")
fi
if [ -n "$OUT_FILE" ]; then
  ARGS+=(--out-file "$OUT_FILE")
fi

exec "$PYTHON_BIN" -m rp_handler.main "${ARGS[@]}"


