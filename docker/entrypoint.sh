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

LOCK_PATH_DEFAULT="/app/lockfiles/comfy-${COMFY_VERSION_NAME:-default}.lock.json"
LOCK_PATH="${LOCK_PATH:-$LOCK_PATH_DEFAULT}"

log_info "COMFY_HOME=$COMFY_HOME"
log_info "MODELS_DIR=$MODELS_DIR"
log_info "LOCK_PATH=$LOCK_PATH"

if [ ! -f "$LOCK_PATH" ]; then
  log_warn "Lock-файл не найден: $LOCK_PATH"
  if [ -n "${COMFY_VERSION_NAME:-}" ]; then
    alt="/app/lockfiles/comfy-$COMFY_VERSION_NAME.lock.json"
    if [ -f "$alt" ]; then
      LOCK_PATH="$alt"
      log_info "Нашёл альтернативный lock-файл: $LOCK_PATH"
    fi
  fi
fi

if [ ! -f "$LOCK_PATH" ]; then
  log_warn "Запуск без lock-файла. Доступны команды handler для справки."
fi

exec python -m rp_handler.main "$@"
