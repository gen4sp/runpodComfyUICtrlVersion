# Реализация версии (versions/\*)

Скрипт `scripts/realize_version.py` разворачивает версию ComfyUI по спецификации `schema_version: 2` из `versions/<id>.json`:

-   резолвит ветки/теги в коммиты и сохраняет `~/.comfy-cache/resolved/<version_id>.lock.json`
-   готовит изолированный `COMFY_HOME` с отдельным `.venv`
-   клонирует ядро и кастом-ноды из кеша/репозиториев, создаёт symlink'и
-   докачивает модели в единый `MODELS_DIR`, генерирует `extra_model_paths.yaml`
-   поддерживает `--dry-run`, `--offline`, `--wheels-dir`

Сценарий одинаков для локальной разработки, RunPod volume и CI.

## Формат JSON‑спеки

```json
{
    "schema_version": 2,
    "version_id": "wan22-fast",
    "comfy": {
        "repo": "https://github.com/comfyanonymous/ComfyUI",
        "ref": "master",
        "commit": "<опционально>"
    },
    "custom_nodes": [
        {
            "repo": "https://github.com/city96/ComfyUI-GGUF",
            "name": "gguf",
            "commit": "<опционально>"
        }
    ],
    "models": [
        {
            "source": "hf://...",
            "name": "wan22-unet",
            "target_subdir": "unet"
        }
    ],
    "env": {
        "HF_TOKEN": "${HF_TOKEN}"
    },
    "options": {
        "offline": false,
        "skip_models": false
    }
}
```

-   `version_id` — имя версии (используется для директорий и resolved-lock)
-   `comfy` — репозиторий ядра, опциональные `ref`/`commit`
-   `custom_nodes` — список узлов (`repo`, опциональные `ref`/`commit`/`name`)
-   `models` — источники моделей (минимум `source`, опционально `name`, `target_subdir`)
-   `env` — дополнительные переменные окружения
-   `options` — дефолтные флаги (`offline`, `skip_models`)

## Команды

### Развёртка по id (ищет `versions/<id>.json`)

```bash
python3 scripts/realize_version.py --version-id wan22-fast
```

### Явный путь к спека‑файлу

```bash
python3 scripts/realize_version.py --spec versions/wan22-fast.json
```

### Дополнительные опции

```bash
python3 scripts/realize_version.py \
  --spec versions/wan22-fast.json \
  --target /runpod-volume/comfy-wan22-fast \
  --wheels-dir /wheels
```

### Dry-run (только показать действия)

```bash
python3 scripts/realize_version.py --version-id wan22-fast --dry-run
```

### Оффлайн режим (без git/pip)

```bash
python3 scripts/realize_version.py --version-id wan22-fast --offline
```

### Пользовательский `COMFY_HOME` и MODELS_DIR

```bash
python3 scripts/realize_version.py \
  --version-id wan22-fast \
  --target /runpod-volume/comfy-wan22-fast \
  --models-dir /workspace/models
```

## Примечания

-   По умолчанию `target` выбирается так: `/runpod-volume/comfy-<id>` (если каталог существует) → `$HOME/comfy-<id>` → `./comfy-<id>`.
-   Каждый `target` содержит отдельный `.venv` (изоляция зависимостей по версии).
-   Модели докачиваются в `MODELS_DIR` (по умолчанию `$target/models`), рядом создаётся `extra_model_paths.yaml`.
-   При наличии `--wheels-dir` все `pip install` выполняются с `--no-index --find-links <dir>`.
