#!/usr/bin/env bash
# shellcheck disable=SC1091

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Strict + logging
if [ -f "$SCRIPT_DIR/lib/strict.sh" ]; then . "$SCRIPT_DIR/lib/strict.sh"; fi
if [ -f "$SCRIPT_DIR/lib/common.sh" ]; then . "$SCRIPT_DIR/lib/common.sh"; fi

usage() {
  cat <<'EOF'
Клонирование окружения ComfyUI по lock-файлу в новую директорию.

Usage:
  scripts/clone_version.sh \
    --lock PATH_TO_LOCK.json \
    --target PATH_TO_NEW_HOME \
    [--python PYTHON_BIN] \
    [--skip-models] \
    [--offline] [--wheels-dir DIR] \
    [--pip-extra-args "...pip args..."]

Env:
  COMFY_HOME   Если не задан --target, может использоваться как целевая директория.

Примеры:
  scripts/clone_version.sh --lock lockfiles/comfy-my.lock.json \
    --target "$HOME/comfy-my"

  scripts/clone_version.sh --lock lockfiles/comfy-my.lock.json \
    --target /runpod-volume/comfy --offline --wheels-dir /wheels
EOF
}

LOCK_PATH=""
TARGET_HOME=""
PYTHON_BIN="${PYTHON_BIN:-python3}"
SKIP_MODELS=0
OFFLINE=0
WHEELS_DIR=""
PIP_EXTRA_ARGS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock)
      LOCK_PATH="$2"; shift 2;;
    --target)
      TARGET_HOME="$2"; shift 2;;
    --python)
      PYTHON_BIN="$2"; shift 2;;
    --skip-models)
      SKIP_MODELS=1; shift;;
    --offline)
      OFFLINE=1; shift;;
    --wheels-dir)
      WHEELS_DIR="$2"; shift 2;;
    --pip-extra-args)
      PIP_EXTRA_ARGS="$2"; shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      log_error "Неизвестный аргумент: $1"; usage; exit 1;;
  esac
done

if [ -z "$LOCK_PATH" ]; then
  log_error "Не указан --lock"; usage; exit 1
fi
if [ ! -f "$LOCK_PATH" ]; then
  log_error "Lock-файл не найден: $LOCK_PATH"; exit 1
fi

if [ -z "$TARGET_HOME" ]; then
  if [ -n "${COMFY_HOME:-}" ]; then
    TARGET_HOME="$COMFY_HOME"
    log_warn "--target не указан, использую COMFY_HOME=$TARGET_HOME"
  else
    log_error "Не указан --target и не задан COMFY_HOME"; exit 1
  fi
fi

# Ensure target path exists
mkdir -p "$TARGET_HOME"

# Prevent accidental overwrite of existing ComfyUI clone
REPO_DIR="$TARGET_HOME/ComfyUI"
if [ -d "$REPO_DIR/.git" ]; then
  log_error "В целевом пути уже есть git-репозиторий: $REPO_DIR — отмена"; exit 1
fi

# Helper: extract JSON values via Python (avoids external deps)
json_eval() {
  local expr="$1"
  "$PYTHON_BIN" - <<PY 2>/dev/null
import json,sys
with open(r"$LOCK_PATH","r",encoding="utf-8") as f:
    d=json.load(f)
v=$expr
if v is None:
    print("")
elif isinstance(v,(str,int,float)):
    print(str(v))
else:
    print("")
PY
}

# Read comfy repo/commit/path
COMFY_REPO="$(json_eval 'd.get("comfyui",{}).get("repo")')"
COMFY_COMMIT="$(json_eval 'd.get("comfyui",{}).get("commit")')"
COMFY_PATH_IN_LOCK="$(json_eval 'd.get("comfyui",{}).get("path")')"

log_info "Целевая директория: $TARGET_HOME"
log_info "ComfyUI repo: ${COMFY_REPO:-<none>} commit: ${COMFY_COMMIT:-<none>}"

mkdir -p "$TARGET_HOME/ComfyUI" "$TARGET_HOME/ComfyUI/custom_nodes" "$TARGET_HOME/models"

# Clone/copy ComfyUI
copy_dir() {
  local src="$1" dst="$2"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --exclude ".git" "$src/" "$dst/"
  else
    mkdir -p "$dst"
    cp -R "$src/" "$dst/"
  fi
}

if [ -n "$COMFY_REPO" ]; then
  log_info "Клонирование ComfyUI: $COMFY_REPO"
  git clone "$COMFY_REPO" "$REPO_DIR"
  if [ -n "$COMFY_COMMIT" ]; then
    log_info "Checkout commit $COMFY_COMMIT"
    git -C "$REPO_DIR" checkout "$COMFY_COMMIT"
  fi
elif [ -n "$COMFY_PATH_IN_LOCK" ] && [ -d "$COMFY_PATH_IN_LOCK" ]; then
  log_warn "В lock отсутствует repo; копирую локальный путь: $COMFY_PATH_IN_LOCK"
  copy_dir "$COMFY_PATH_IN_LOCK" "$REPO_DIR"
else
  log_error "Невозможно получить ComfyUI: ни repo, ни доступный локальный path"; exit 1
fi

# Clone custom nodes
log_info "Обработка custom_nodes из lock"
"$PYTHON_BIN" - <<'PY' | while IFS=$'\t' read -r NAME REPO COMMIT PATHVAL; do
import json,sys
from pathlib import Path
lock_path = r"$LOCK_PATH"
with open(lock_path,"r",encoding="utf-8") as f:
    d=json.load(f)
nodes = d.get("custom_nodes", [])
for n in nodes:
    name = str(n.get("name") or "node").strip()
    repo = str(n.get("repo") or "").strip()
    commit = str(n.get("commit") or "").strip()
    path = str(n.get("path") or "").strip()
    # Use tabs to avoid spaces in values
    print("{}\t{}\t{}\t{}".format(name, repo, commit, path))
PY
  DEST="$REPO_DIR/custom_nodes/$NAME"
  if [ -n "$REPO" ]; then
    log_info "  Клонирование узла $NAME из $REPO"
    git clone "$REPO" "$DEST"
    if [ -n "$COMMIT" ]; then
      git -C "$DEST" checkout "$COMMIT" || log_warn "Не удалось checkout $COMMIT для $NAME"
    fi
  elif [ -n "$PATHVAL" ] && [ -d "$PATHVAL" ]; then
    log_warn "  Узел $NAME без repo; копирую из $PATHVAL"
    copy_dir "$PATHVAL" "$DEST"
  else
    log_warn "  Пропуск узла $NAME: нет repo и недоступен path"
  fi
done

# Python venv
VENV_PATH="$TARGET_HOME/.venv"
if [ ! -d "$VENV_PATH" ]; then
  log_info "Создание venv: $VENV_PATH"
  "$PYTHON_BIN" -m venv "$VENV_PATH"
else
  log_info "Использую существующий venv: $VENV_PATH"
fi
# shellcheck source=/dev/null
. "$VENV_PATH/bin/activate"
python -V
if [ "$OFFLINE" != "1" ]; then
  pip install -U pip setuptools wheel || log_warn "Не удалось обновить pip/setuptools/wheel"
else
  log_info "OFFLINE режим: пропуск обновления pip/setuptools/wheel"
fi

# Compose requirements from lock
REQ_LOCK_FILE="$TARGET_HOME/.requirements.lock.txt"
log_info "Генерация pinned requirements из lock: $REQ_LOCK_FILE"
python - <<'PY'
import json,sys
lock_path = r"$LOCK_PATH"
out_path = r"$REQ_LOCK_FILE"
with open(lock_path,"r",encoding="utf-8") as f:
    d=json.load(f)
packages = d.get("python",{}).get("packages", [])
lines = []
for p in packages:
    name = (p.get("name") or "").strip()
    url = (p.get("url") or "").strip()
    ver = (p.get("version") or "").strip()
    if url:
        lines.append(f"{name} @ {url}")
    elif ver:
        lines.append(f"{name}=={ver}")
    elif name:
        # fallback (не рекомендуется)
        lines.append(name)
open(out_path,"w",encoding="utf-8").write("\n".join(lines)+("\n" if lines else ""))
print(out_path)
PY

# Install requirements
PIP_ARGS=( "-r" "$REQ_LOCK_FILE" )
if [ "$OFFLINE" = "1" ]; then
  if [ -z "$WHEELS_DIR" ]; then
    log_warn "--offline без --wheels-dir: pip будет использовать только кэш"
  else
    PIP_ARGS=( "--no-index" "--find-links" "$WHEELS_DIR" "-r" "$REQ_LOCK_FILE" )
  fi
fi
if [ -n "$PIP_EXTRA_ARGS" ]; then
  # shellcheck disable=SC2206
  EXTRA_ARR=( $PIP_EXTRA_ARGS )
  PIP_ARGS=( "${EXTRA_ARR[@]}" "${PIP_ARGS[@]}" )
fi
log_info "Установка Python-зависимостей (может занять время)"
pip install "${PIP_ARGS[@]}"

# Optionally verify models
if [ "$SKIP_MODELS" = "0" ]; then
  log_info "Верификация/восстановление моделей по lock"
  COMFY_HOME="$TARGET_HOME" "$PYTHON_BIN" "$SCRIPT_DIR/verify_models.py" \
    --lock "$LOCK_PATH" \
    --models-dir "$TARGET_HOME/models" \
    --verbose || log_warn "Верификация моделей завершилась с ошибками"
else
  log_info "Пропуск верификации моделей (--skip-models)"
fi

# Create environment marker for safe removal
printf "lock=%s\n" "$LOCK_PATH" > "$TARGET_HOME/.comfy_env"

log_ok "Клон готов: $TARGET_HOME"
cat <<EON
Чтобы запустить локально:
  source "$VENV_PATH/bin/activate"
  python "$REPO_DIR/main.py"
EON


