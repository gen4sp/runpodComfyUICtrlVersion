#!/usr/bin/env bash
# shellcheck disable=SC1091

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/lib/strict.sh" ]; then . "$SCRIPT_DIR/lib/strict.sh"; fi
if [ -f "$SCRIPT_DIR/lib/common.sh" ]; then . "$SCRIPT_DIR/lib/common.sh"; fi

usage() {
  cat <<'EOF'
Безопасное удаление окружения ComfyUI, созданного init/clone скриптами.

Usage:
  scripts/remove_version.sh --target PATH [--yes] [--remove-models] [--remove-root] [--dry-run]

Опции:
  --target PATH      Корень окружения (COMFY_HOME), обязательный, если не задан $COMFY_HOME.
  --yes              Не задавать вопросов (non-interactive), подтверждает удаление безопасных путей.
  --remove-models    Также удалить директорию models внутри target.
  --remove-root      Удалить сам корневой каталог после очистки (если пуст или с флагом --yes).
  --dry-run          Только показать, что будет удалено, без фактического удаления.

Критерии безопасности:
  - Путь должен содержать подкаталог "ComfyUI" или файл-маркер ".comfy_env".
  - Не удаляем "/", "$HOME" и другие слишком короткие/подозрительные пути.
EOF
}

TARGET_HOME="${COMFY_HOME:-}"
ASSUME_YES=0
REMOVE_MODELS=0
REMOVE_ROOT=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET_HOME="$2"; shift 2;;
    --yes)
      ASSUME_YES=1; shift;;
    --remove-models)
      REMOVE_MODELS=1; shift;;
    --remove-root)
      REMOVE_ROOT=1; shift;;
    --dry-run)
      DRY_RUN=1; shift;;
    -h|--help)
      usage; exit 0;;
    *)
      log_error "Неизвестный аргумент: $1"; usage; exit 1;;
  esac
done

if [ -z "$TARGET_HOME" ]; then
  log_error "Не указан --target и не задан COMFY_HOME"; usage; exit 1
fi

# Resolve absolute path and basic safety checks
TARGET_HOME="$(cd "$TARGET_HOME" 2>/dev/null && pwd || echo "")"
if [ -z "$TARGET_HOME" ]; then
  log_error "Целевая директория не существует"; exit 1
fi

case "$TARGET_HOME" in
  "/"|"/home"|"/Users"|"/Users/$USER"|"/home/$USER")
    log_error "Опасный путь для удаления: $TARGET_HOME"; exit 1;;
esac

if [ ${#TARGET_HOME} -lt 6 ]; then
  log_error "Слишком короткий путь: $TARGET_HOME"; exit 1
fi

MARKER_FILE="$TARGET_HOME/.comfy_env"
COMFY_DIR="$TARGET_HOME/ComfyUI"

if [ ! -f "$MARKER_FILE" ] && [ ! -d "$COMFY_DIR" ]; then
  log_error "Не найден ни маркер .comfy_env, ни каталог ComfyUI в $TARGET_HOME — отмена"; exit 1
fi

queue_rm() { echo "$1"; }

TO_REMOVE=()
if [ -d "$COMFY_DIR" ]; then TO_REMOVE+=("$COMFY_DIR"); fi
if [ -d "$TARGET_HOME/.venv" ]; then TO_REMOVE+=("$TARGET_HOME/.venv"); fi
if [ -f "$TARGET_HOME/.requirements.lock.txt" ]; then TO_REMOVE+=("$TARGET_HOME/.requirements.lock.txt"); fi
if [ -f "$MARKER_FILE" ]; then TO_REMOVE+=("$MARKER_FILE"); fi
if [ "$REMOVE_MODELS" = "1" ] && [ -d "$TARGET_HOME/models" ]; then TO_REMOVE+=("$TARGET_HOME/models"); fi

if [ ${#TO_REMOVE[@]} -eq 0 ]; then
  log_warn "Нечего удалять в $TARGET_HOME"; exit 0
fi

log_info "К удалению (${#TO_REMOVE[@]}):"
for p in "${TO_REMOVE[@]}"; do
  echo "  $p"
done

if [ "$DRY_RUN" = "1" ]; then
  log_ok "Dry-run завершен"; exit 0
fi

if [ "$ASSUME_YES" != "1" ]; then
  log_error "Требуется подтверждение (--yes) для non-interactive удаления"; exit 1
fi

for p in "${TO_REMOVE[@]}"; do
  if [ -d "$p" ]; then
    rm -rf -- "$p"
  else
    rm -f -- "$p"
  fi
done

if [ "$REMOVE_ROOT" = "1" ]; then
  # Try to remove the root if empty; with --yes allow removing regardless of emptiness
  if [ "$ASSUME_YES" = "1" ]; then
    rmdir "$TARGET_HOME" 2>/dev/null || true
    if [ -d "$TARGET_HOME" ]; then
      # If still not empty, force remove only if --yes and path still looks safe
      log_warn "Корень не пуст, пропускаю удаление root"
    fi
  fi
fi

log_ok "Удаление завершено: $TARGET_HOME"


