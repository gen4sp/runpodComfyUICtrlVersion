#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log_info() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$*"; }
log_warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$*"; }
log_error() { printf "%b[ERROR]%b %s\n" "$RED" "$NC" "$*"; }
log_ok() { printf "%b[OK]%b %s\n" "$GREEN" "$NC" "$*"; }

: "${COMFY_HOME:=/runpod-volume/ComfyUI}"
: "${MODELS_DIR:=/runpod-volume/models}"

log_info "COMFY_HOME=$COMFY_HOME"
log_info "MODELS_DIR=$MODELS_DIR"

# Настройка путей к монтированным директориям
MOUNT_BASE="/runpod-volume/runpodComfyUICtrlVersion"

# Ожидание монтирования volume с таймаутом
VOLUME_WAIT_TIMEOUT=60
VOLUME_WAIT_COUNT=0
log_info "Проверка доступности volume..."

while [ ! -d "/runpod-volume" ] && [ $VOLUME_WAIT_COUNT -lt $VOLUME_WAIT_TIMEOUT ]; do
    if [ $((VOLUME_WAIT_COUNT % 10)) -eq 0 ]; then
        log_warn "Ожидание монтирования /runpod-volume... (${VOLUME_WAIT_COUNT}s/${VOLUME_WAIT_TIMEOUT}s)"
    fi
    sleep 1
    VOLUME_WAIT_COUNT=$((VOLUME_WAIT_COUNT + 1))
done

if [ -d "/runpod-volume" ]; then
    log_ok "Volume /runpod-volume успешно примонтирован"
else
    log_error "КРИТИЧНО: /runpod-volume не примонтирован после ${VOLUME_WAIT_TIMEOUT}s!"
    log_error "Контейнер не может работать без volume. Проверьте настройки Network Volume в RunPod."
    exit 1
fi

# Дополнительно: ждём доступности директории с кодом
if [ ! -d "$MOUNT_BASE" ]; then
    log_warn "Директория $MOUNT_BASE не найдена на volume"
    log_warn "Убедитесь, что код размещён в правильной директории на volume"
fi

# Создаём симлинки на монтированные директории
if [ -d "$MOUNT_BASE/scripts" ]; then
    ln -sf "$MOUNT_BASE/scripts" /app/scripts
    log_info "Смонтирована директория scripts: $MOUNT_BASE/scripts -> /app/scripts"
else
    log_warn "Директория scripts не найдена в $MOUNT_BASE/scripts"
fi

if [ -d "$MOUNT_BASE/rp_handler" ]; then
    ln -sf "$MOUNT_BASE/rp_handler" /app/rp_handler
    log_info "Смонтирована директория rp_handler: $MOUNT_BASE/rp_handler -> /app/rp_handler"
else
    log_warn "Директория rp_handler не найдена в $MOUNT_BASE/rp_handler"
fi

if [ -d "$MOUNT_BASE/versions" ]; then
    ln -sf "$MOUNT_BASE/versions" /app/versions
    log_info "Смонтирована директория versions: $MOUNT_BASE/versions -> /app/versions"
else
    log_warn "Директория versions не найдена в $MOUNT_BASE/versions"
fi

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
    if [ $# -gt 0 ]; then
      log_warn "Игнорирую дополнительные аргументы для serverless: $*"
    fi
    log_info "Starting serverless adapter"
    exec python -m rp_handler.serverless
    ;;
  cli)
    shift || true
    log_info "Starting CLI handler"
    exec python -m rp_handler.main "$@"
    ;;
  *)
    if [ "$force_serverless" = "1" ]; then
      log_info "RUNPOD_SERVERLESS=true — принудительно запускаю serverless"
      exec python -m rp_handler.serverless
    else
      log_warn "Неизвестный аргумент '$first_arg' — fallback к serverless"
      exec python -m rp_handler.serverless
    fi
    ;;
esac
