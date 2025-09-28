#!/usr/bin/env bash
# shellcheck disable=SC1091

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Strict + logging
if [ -f "$SCRIPT_DIR/lib/strict.sh" ]; then . "$SCRIPT_DIR/lib/strict.sh"; fi
if [ -f "$SCRIPT_DIR/lib/common.sh" ]; then . "$SCRIPT_DIR/lib/common.sh"; fi

usage() {
  cat <<'EOF'
Инициализация ComfyUI: клонирование репозитория, создание venv и установка базовых зависимостей.

Usage:
  scripts/init_comfyui.sh [--path PATH] [--repo URL] [--ref REF] \
                          [--venv PATH] [--install-torch auto|cpu|skip] \
                          [--python PYTHON]

Env:
  COMFY_HOME     Базовая директория установки (аналог --path)
  PYTHON_BIN     Исполняемый Python (по умолчанию: python3)

Примеры:
  COMFY_HOME="$HOME/comfy" scripts/init_comfyui.sh --install-torch auto
  scripts/init_comfyui.sh --path /runpod-volume/builds/comfy --install-torch skip
EOF
}

# Defaults
COMFY_REPO_DEFAULT="https://github.com/comfyanonymous/ComfyUI.git"
PYTHON_BIN="${PYTHON_BIN:-python3}"
COMFY_HOME="${COMFY_HOME:-}"
COMFY_REPO="${COMFY_REPO:-$COMFY_REPO_DEFAULT}"
COMFY_REF="${COMFY_REF:-}"
VENV_PATH="${VENV_PATH:-}"
INSTALL_TORCH="${INSTALL_TORCH:-skip}" # auto|cpu|skip

# Arg parse
while [[ $# -gt 0 ]]; do
  case "$1" in
    --path)
      COMFY_HOME="$2"; shift 2;;
    --repo)
      COMFY_REPO="$2"; shift 2;;
    --ref)
      COMFY_REF="$2"; shift 2;;
    --venv)
      VENV_PATH="$2"; shift 2;;
    --install-torch)
      INSTALL_TORCH="$2"; shift 2;;
    --python)
      PYTHON_BIN="$2"; shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      log_error "Неизвестный аргумент: $1"; usage; exit 1;;
  esac
done

if [ -z "$COMFY_HOME" ]; then
  COMFY_HOME="$(pwd)/comfy"
  log_warn "COMFY_HOME не задан, использую по умолчанию: $COMFY_HOME"
fi

if [ -z "$VENV_PATH" ]; then
  VENV_PATH="$COMFY_HOME/.venv"
fi

REPO_DIR="$COMFY_HOME"

mkdir -p "$COMFY_HOME"

# Clone or update
if [ -d "$REPO_DIR/.git" ]; then
  log_info "Обновление репозитория: $REPO_DIR"
  git -C "$REPO_DIR" fetch --all --prune
else
  log_info "Клонирование $COMFY_REPO в $REPO_DIR"
  git clone "$COMFY_REPO" "$REPO_DIR"
fi

if [ -n "$COMFY_REF" ]; then
  log_info "Checkout на ref: $COMFY_REF"
  git -C "$REPO_DIR" checkout "$COMFY_REF"
  # Попытка fast-forward, если это ветка
  git -C "$REPO_DIR" pull --ff-only || true
fi

# Python venv
if [ ! -d "$VENV_PATH" ]; then
  log_info "Создание venv: $VENV_PATH"
  "$PYTHON_BIN" -m venv "$VENV_PATH"
else
  log_info "Использую существующий venv: $VENV_PATH"
fi
# shellcheck source=/dev/null
. "$VENV_PATH/bin/activate"

python -V
pip install -U pip setuptools wheel

# Optional torch
install_torch() {
  case "$1" in
    skip|no|none)
      log_info "Пропуск установки torch";;
    auto|cpu|yes)
      if [ "$(uname -s)" = "Darwin" ]; then
        log_info "Установка torch (macOS)"
        pip install -U torch torchvision || log_warn "Не удалось установить torch; продолжу"
      else
        log_info "Установка torch CPU (Linux/прочее)"
        pip install -U --index-url https://download.pytorch.org/whl/cpu torch torchvision || log_warn "Не удалось установить torch; продолжу"
      fi;;
    *)
      log_warn "Неизвестный режим установки torch: $1 — пропускаю";;
  esac
}
install_torch "$INSTALL_TORCH"

# ComfyUI requirements
REQ_FILE="$REPO_DIR/requirements.txt"
if [ -f "$REQ_FILE" ]; then
  log_info "Установка зависимостей из $REQ_FILE"
  pip install -r "$REQ_FILE"
else
  log_warn "requirements.txt не найден в $REPO_DIR — пропускаю"
fi

log_ok "Готово. ComfyUI: $REPO_DIR"
cat <<EON
Чтобы запустить локально:
  source "$VENV_PATH/bin/activate"
  cd "$REPO_DIR"
  python main.py
EON
