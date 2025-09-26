# Установка кастом нод и зависимостей

```bash
python3 scripts/validate_json_nodes.py --install-reqs --verbose
```

## Установка кастом нод вручную

### Из GitHub (автоматическая установка)

```bash
cd "$COMFY_HOME"
source .venv/bin/activate
git clone https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
cd custom_nodes/ComfyUI-GGUF
pip install -r requirements.txt
```

### Из Hugging Face

```bash
cd "$COMFY_HOME"
source .venv/bin/activate
git clone https://huggingface.co/spaces/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
cd custom_nodes/ComfyUI-GGUF
pip install -r requirements.txt
```

## Проверка установки кастом нод

```bash
cd "$COMFY_HOME"
python3 scripts/validate_json_nodes.py --validate-only --verbose
```

## Обновление кастом нод

```bash
cd "$COMFY_HOME/custom_nodes/ComfyUI-GGUF"
git pull
cd "$COMFY_HOME"
source .venv/bin/activate
pip install -r custom_nodes/ComfyUI-GGUF/requirements.txt --upgrade
```

## Удаление кастом нод

```bash
cd "$COMFY_HOME"
rm -rf custom_nodes/ComfyUI-GGUF
```

## Создание версии с кастом нодами

```bash
python3 scripts/create_version.py \
  --name "with-gguf" \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf \
  --custom-node repo=https://github.com/kijai/ComfyUI-WanVideoWrapper,name=wan-wrapper \
  --requirements ./requirements.txt \
  --pretty
```

## Популярные кастом ноды

### Для FLUX

-   `https://github.com/city96/ComfyUI-GGUF` — GGUF загрузчик
-   `https://github.com/kijai/ComfyUI-FluxTrainer` — Flux trainer
-   `https://github.com/XLabs-AI/x-flux-comfyui` — X-Flux

### Для Wan

-   `https://github.com/kijai/ComfyUI-WanVideoWrapper` — Wan Video wrapper
-   `https://github.com/city96/ComfyUI-GGUF` — GGUF загрузчик

### Для Stable Diffusion

-   `https://github.com/comfyanonymous/ComfyUI_experiments` — экспериментальные ноды
-   `https://github.com/ltdrdata/ComfyUI-Manager` — менеджер нод

### Для видео

-   `https://github.com/kijai/ComfyUI-VideoHelperSuite` — видео хелперы
-   `https://github.com/Fannovel16/comfyui_controlnet_aux` — ControlNet aux

## Проверка зависимостей в venv

```bash
cd "$COMFY_HOME"
source .venv/bin/activate
pip list | grep torch
pip list | grep torchvision
```

## Создание нового requirements.txt из venv

```bash
cd "$COMFY_HOME"
source .venv/bin/activate
pip freeze > requirements-new.txt
```

## Управление кастом-нодами через JSON-спецификации

### Создание JSON-файлов с нодами

Создайте файл `nodes/your_nodes.json` с описанием нод:

```json
[
    {
        "name": "ComfyUI-GGUF",
        "repo": "https://github.com/city96/ComfyUI-GGUF",
        "commit": "main",
        "target_dir": "$COMFY_HOME/custom_nodes/ComfyUI-GGUF",
        "install_requirements": true
    },
    {
        "name": "ComfyUI-WanVideoWrapper",
        "repo": "https://github.com/kijai/ComfyUI-WanVideoWrapper",
        "commit": "a1b2c3d",
        "install_requirements": true
    }
]
```

**Поля JSON:**

-   `name` (обязательно) — имя директории ноды
-   `repo` (обязательно) — git URL (https/ssh)
-   `commit` (опционально) — фиксируемый коммит/тег/ветка (по умолчанию `main`)
-   `target_dir` (опционально) — путь checkout (по умолчанию `$COMFY_HOME/custom_nodes/${name}`)
-   `install_requirements` (опционально) — устанавливать ли `requirements.txt` (по умолчанию `true`)

### Валидация и установка нод

```bash
# Валидация всех JSON в каталоге nodes/
python3 scripts/validate_json_nodes.py --verbose

# Валидация конкретного файла
python3 scripts/validate_json_nodes.py --json nodes/wan_nodes.json --verbose

# Установка с requirements
python3 scripts/validate_json_nodes.py --json nodes/wan_nodes.json --install-reqs --verbose

# Перезапись существующих репозиториев
python3 scripts/validate_json_nodes.py --overwrite --install-reqs --verbose

# Только валидация без установки
python3 scripts/validate_json_nodes.py --validate-only --verbose
```

**Параметры validate_json_nodes.py:**

-   `--json FILE` — JSON файлы для обработки (можно несколько)
-   `--comfy-home PATH` — путь к ComfyUI (по умолчанию `$COMFY_HOME` или `./comfy`)
-   `--validate-only` — только валидация, без установки
-   `--overwrite` — перезаписать существующие репозитории
-   `--install-reqs` — установить requirements.txt
-   `--workers N` — количество параллельных потоков (по умолчанию 4)
-   `--verbose` — подробный вывод

### Восстановление нод из lock-файлов

```bash
# Восстановление из всех lock-файлов
python3 scripts/verify_custom_nodes.py --verbose

# Восстановление из конкретного lock-файла
python3 scripts/verify_custom_nodes.py --lock-files lockfiles/comfy-my-version.lock.json --verbose

# Восстановление с установкой requirements
python3 scripts/verify_custom_nodes.py --install-reqs --verbose

# Перезапись существующих репозиториев
python3 scripts/verify_custom_nodes.py --overwrite --install-reqs --verbose
```

**Параметры verify_custom_nodes.py:**

-   `--lock-files FILE` — lock файлы для обработки (можно несколько)
-   `--comfy-home PATH` — путь к ComfyUI (по умолчанию `$COMFY_HOME` или `./comfy`)
-   `--overwrite` — перезаписать существующие репозитории
-   `--install-reqs` — установить requirements.txt
-   `--workers N` — количество параллельных потоков (по умолчанию 4)
-   `--verbose` — подробный вывод

### Работа с виртуальным окружением

Скрипты автоматически определяют виртуальное окружение:

-   Если существует `$COMFY_HOME/.venv` — используется `pip` из venv
-   Иначе используется системный `pip`

```bash
# Проверка используемого pip
python3 scripts/validate_json_nodes.py --json nodes/wan_nodes.json --install-reqs --verbose
```

### Примеры использования

```bash
# Создание и установка набора нод для FLUX
echo '[
  {
    "name": "ComfyUI-GGUF",
    "repo": "https://github.com/city96/ComfyUI-GGUF",
    "commit": "main",
    "install_requirements": true
  },
  {
    "name": "ComfyUI-FluxTrainer",
    "repo": "https://github.com/kijai/ComfyUI-FluxTrainer",
    "commit": "main",
    "install_requirements": true
  }
]' > nodes/flux_nodes.json

python3 scripts/validate_json_nodes.py --json nodes/flux_nodes.json --install-reqs --verbose
```

### Интеграция с create_version.py

```bash
# Создание версии с JSON-нодами
python3 scripts/create_version.py \
  --name "flux-with-json-nodes" \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf \
  --custom-node repo=https://github.com/kijai/ComfyUI-FluxTrainer,name=flux-trainer \
  --requirements ./requirements.txt \
  --pretty

# Восстановление нод из созданного lock-файла
python3 scripts/verify_custom_nodes.py --lock-files lockfiles/comfy-flux-with-json-nodes.lock.json --install-reqs --verbose
```
