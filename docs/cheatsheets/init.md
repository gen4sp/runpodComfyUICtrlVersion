# Инициализация ComfyUI

## Локальная инициализация с базовым Torch

```bash
export COMFY_HOME="$HOME/comfy"
./scripts/init_comfyui.sh --install-torch auto
```

## Инициализация на RunPod volume (без Torch)

```bash
./scripts/init_comfyui.sh --path /runpod-volume/comfy --install-torch skip
```

## Инициализация с конкретной версией ComfyUI

```bash
export COMFY_HOME="$HOME/comfy"
./scripts/init_comfyui.sh --repo https://github.com/comfyanonymous/ComfyUI.git --ref v0.1.0 --install-torch auto
```

## Запуск ComfyUI после инициализации

```bash
source "$COMFY_HOME/.venv/bin/activate"
cd "$COMFY_HOME"
python main.py
```

## Параметры скрипта init_comfyui.sh

-   `--path PATH` — путь установки ComfyUI (по умолчанию: ./comfy или $COMFY_HOME)
-   `--repo URL` — репозиторий ComfyUI (по умолчанию: https://github.com/comfyanonymous/ComfyUI.git)
-   `--ref REF` — ветка/тег/commit для checkout
-   `--venv PATH` — путь к виртуальному окружению (по умолчанию: $COMFY_HOME/.venv)
-   `--install-torch auto|cpu|skip` — установка PyTorch (по умолчанию: skip)
-   `--python PYTHON` — путь к исполняемому Python (по умолчанию: python3)

## Переменные окружения

-   `COMFY_HOME` — базовая директория установки
-   `PYTHON_BIN` — исполняемый Python (по умолчанию: python3)
