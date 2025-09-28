#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log_info() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$*"; }
log_warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$*"; }
log_error() { printf "%b[ERROR]%b %s\n" "$RED" "$NC" "$*"; }
log_ok() { printf "%b[OK]%b %s\n" "$GREEN" "$NC" "$*"; }

: "${COMFY_HOME:=/workspace/ComfyUI}"
: "${MODELS_DIR:=/workspace/models}"

log_info "COMFY_HOME=$COMFY_HOME"
log_info "MODELS_DIR=$MODELS_DIR"

log_info "ENTRYPOINT_ARGS=$*"

if [ -n "${RUNPOD_TEMPLATE_ID:-}" ]; then
  log_info "RUNPOD_TEMPLATE_ID=${RUNPOD_TEMPLATE_ID}"
fi

if [ -n "${RUNPOD_SERVERLESS:-}" ]; then
  log_info "RUNPOD_SERVERLESS=${RUNPOD_SERVERLESS}"
fi

first_arg="${1:-}"

# Простейшая проверка truthy значений для RUNPOD_SERVERLESS
runpod_serverless_flag="${RUNPOD_SERVERLESS:-}"
case "${runpod_serverless_flag,,}" in
  1|true|yes|on)
    force_serverless=1
    ;;
  *)
    force_serverless=0
    ;;
esac

if [ -z "$first_arg" ]; then
  first_arg="serverless"
fi

case "$first_arg" in
  serverless)
    if [ $# -gt 0 ]; then
      shift
    fi
    log_info "Starting serverless adapter"
    exec python -m rp_handler.serverless "$@"
    ;;
  cli)
    shift || true
    log_info "Starting CLI handler"
    exec python -m rp_handler.main "$@"
    ;;
  *)
    if [ "$force_serverless" = "1" ]; then
      log_info "RUNPOD_SERVERLESS=true — принудительно запускаю serverless"
      exec python -m rp_handler.serverless "$@"
    else
      log_warn "Неизвестный аргумент '$first_arg' — fallback к serverless"
      exec python -m rp_handler.serverless "$@"
    fi
    ;;
esac
