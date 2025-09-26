## ComfyUI Version Control — 1‑Page Manual

Краткое руководство по воспроизводимым версиям ComfyUI для локальной работы, Docker и RunPod. Все операции базируются на единой спецификации `versions/<id>.json` (schema v2).

### Предусловия

-   Python 3.11+ и `venv`
-   Docker (для контейнера)
-   macOS/Linux или RunPod (Pods/serverless)

### Основные сущности

-   `versions/<id>.json` — спецификация версии (ядро, кастом‑ноды, модели, опции)
-   `COMFY_HOME` — директория окружения версии (создаётся при развертке)
-   `MODELS_DIR` — директория моделей (по умолчанию `$COMFY_HOME/models`)

### Быстрый старт

1. Инициализация ComfyUI (опционально, для локальной разработки):

```bash
export COMFY_HOME="$HOME/comfy"
./scripts/init_comfyui.sh --install-torch auto
```

2. Создание версии (lock beta) — по желанию, чтобы зафиксировать текущую установку:

```bash
python3 scripts/create_version.py \
  --name "my-version" \
  --comfy-path "$COMFY_HOME" \
  --models-spec ./models/wan22-fast-models.yml \
  --pretty
```

3. Оформите спецификацию версии `versions/my-version.json` (schema v2):

```json
{
    "schema_version": 2,
    "version_id": "my-version",
    "comfy": {
        "repo": "https://github.com/comfyanonymous/ComfyUI",
        "ref": "master"
    },
    "custom_nodes": [],
    "models": []
}
```

4. Развернуть окружение версии (создаст изолированный `.venv`, подтянет ноды и модели):

```bash
python3 scripts/realize_version.py --version-id "my-version"
```

5. Запустить workflow локально через handler:

```bash
./scripts/run_handler_local.sh \
  --version-id "my-version" \
  --workflow ./workflows/minimal.json \
  --output base64
```

### Команды высокого уровня (Version CLI)

```bash
# Разрешить ссылки (ref → commit) и сохранить resolved-lock
python3 scripts/version.py resolve my-version

# Развернуть окружение (план → установка)
python3 scripts/version.py realize my-version --dry-run
python3 scripts/version.py realize my-version

# Протестировать выполнение workflow
python3 scripts/version.py test my-version --workflow ./workflows/minimal.json --output base64
```

### Модели

-   YAML примеры лежат в `models/*.yml`. Скачать/проверить можно:

```bash
python3 scripts/verify_models.py --lock lockfiles/comfy-my-version.lock.json --models-dir "$COMFY_HOME/models"
```

HF/Civitai токены: `HF_TOKEN`, `CIVITAI_TOKEN`.

### Docker и RunPod

Собрать образ:

```bash
./scripts/build_docker.sh --version "my-version" --tag runpod-comfy:local
```

Запуск внутри контейнера:

```bash
docker run --rm \
  -e COMFY_VERSION_NAME="my-version" \
  runpod-comfy:local \
  --help | cat
```

Запуск handler в контейнере:

```bash
docker run --rm \
  -e COMFY_VERSION_NAME="my-version" \
  runpod-comfy:local \
  --version-id "my-version" \
  --workflow /app/workflows/minimal.json \
  --output base64 | cat
```

RunPod Pods (volume): используйте `COMFY_HOME=/runpod-volume/comfy-<id>` и выполните `scripts/realize_version.py --version-id <id>` один раз на volume.

### Полезные переменные окружения

-   `COMFY_HOME`, `MODELS_DIR`
-   `OUTPUT_MODE` = `gcs` | `base64` (по умолчанию `gcs`)
-   GCS: `GCS_BUCKET`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`/`GCS_PROJECT`, `GCS_PREFIX`

### Где смотреть дальше

-   `docs/instructions.md` — подробные флаги и сценарии
-   `docs/cheatsheets/README.md` — быстрые команды по этапам
-   `docs/runpod.md` — специфично для RunPod
