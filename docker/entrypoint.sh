#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log_info() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$*"; }
log_warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$*"; }
log_error() { printf "%b[ERROR]%b %s\n" "$RED" "$NC" "$*"; }
log_ok() { printf "%b[OK]%b %s\n" "$GREEN" "$NC" "$*"; }

: "${COMFY_HOME:=/opt/comfy}"
: "${MODELS_DIR:=/opt/comfy/models}"

log_info "COMFY_HOME=$COMFY_HOME"
log_info "MODELS_DIR=$MODELS_DIR"
SPEC_PATH_DEFAULT="/app/versions/${COMFY_VERSION_NAME:-default}.json"
SPEC_PATH="${VERSION_SPEC_PATH:-$SPEC_PATH_DEFAULT}"
log_info "VERSION_SPEC_PATH=$SPEC_PATH"

if [ ! -f "$SPEC_PATH" ]; then
  log_warn "Spec-файл не найден: $SPEC_PATH"
  log_warn "Передайте --version-id или смонтируйте versions/<id>.json"
fi

exec python -m rp_handler.main "$@"
