## Руководство по использованию

Данный документ описывает, как пользоваться инструментами для управления версиями ComfyUI, локально и в Docker/RunPod.

### Предварительные требования

-   macOS, установленный Docker, Python 3.11+.
-   Доступ к интернету для скачивания зависимостей и моделей (или подготовленные wheel-артефакты и локальные источники).
-   (Опционально) Доступ к Google Cloud Storage для загрузки результатов.

### Переменные окружения

-   `COMFY_HOME` — базовая директория установки ComfyUI (локально или путь volume на RunPod).
-   `MODELS_DIR` — базовая директория моделей (по умолчанию `$COMFY_HOME/models`).
-   `COMFY_VERSION_NAME` — удобное имя версии (используется для поиска `versions/<id>.json`).
-   `OUTPUT_MODE` — режим вывода результата: `gcs` (по умолчанию) или `base64`.
-   `GCS_BUCKET` — имя bucket для загрузки результатов (используется по умолчанию).
-   `GOOGLE_APPLICATION_CREDENTIALS` — путь к JSON ключу сервисного аккаунта (обязателен для GCS).
-   `GOOGLE_CLOUD_PROJECT` — ID проекта GCP (или `GCS_PROJECT`).
-   `GCS_PREFIX` — префикс ключа в bucket (по умолчанию `comfy/outputs`).
-   `GCS_RETRIES` — количество попыток при загрузке (по умолчанию 3).
-   `GCS_RETRY_BASE_SLEEP` — базовая задержка перед повтором (сек, по умолчанию 0.5).
-   `GCS_PUBLIC` — если `true`, объекту ставится ACL public-read.
-   `GCS_SIGNED_URL_TTL` — если >0, будет сгенерирован подписанный URL на TTL секунд (печатается в verbose-логе).
-   `GCS_VALIDATE` — если `true` (по умолчанию), выполняется базовая проверка доступа к bucket при старте.

### Инициализация ComfyUI

Скрипт `scripts/init_comfyui.sh` клонирует репозиторий ComfyUI, создает `venv` и устанавливает базовые зависимости.

Параметры:

-   `--path PATH` — путь установки (`COMFY_HOME`). По умолчанию: `./comfy`.
-   `--repo URL` — репозиторий ComfyUI. По умолчанию: `https://github.com/comfyanonymous/ComfyUI.git`.
-   `--ref REF` — ветка/тег/commit для checkout.
-   `--venv PATH` — путь к виртуальному окружению. По умолчанию: `$COMFY_HOME/.venv`.
-   `--install-torch auto|cpu|skip` — установка PyTorch (по умолчанию `skip`). На macOS ставится обычный билд, на Linux — CPU wheels.
-   `--python PYTHON` — путь к исполняемому Python (по умолчанию `python3`).

Примеры:

```bash
export COMFY_HOME="$HOME/comfy"
./scripts/init_comfyui.sh --install-torch auto
```

RunPod volume:

```bash
./scripts/init_comfyui.sh --path /runpod-volume/comfy --install-torch skip
```

Запуск ComfyUI после инициализации:

```bash
source "$COMFY_HOME/.venv/bin/activate"
python "$COMFY_HOME/ComfyUI/main.py"
```

### Создание спецификации версии (schema v2)

Все операции строятся вокруг `versions/<id>.json`. Для генерации используйте CLI:

```bash
python3 scripts/version.py create "$COMFY_VERSION_NAME" \
  --repo https://github.com/comfyanonymous/ComfyUI@main \
  --nodes https://github.com/comfyanonymous/ComfyUI-Custom-Scripts@main \
  --models '{"source": "https://example.com/model.safetensors", "target_subdir": "checkpoints"}'
```

Аргументы:

-   `--repo` — обязательный. URL ядра ComfyUI с опциональным `@ref`. Реф резолвится в commit через `git ls-remote`.
-   `--nodes` — повторяемый. Принимает JSON-объект, путь к файлу или строку `<repo>@<ref>`. Если `commit` не указан, вычисляется автоматически.
-   `--models` — повторяемый. Принимает JSON-объект или файл со списком объектов. Поля: `source`, `target_subdir?`, `target_path?`, `name?`, `checksum?`.
-   `--models-root` — директория с локальными моделями для авто-расчёта checksum.
-   `--auto-checksum` — если задан, для найденных локальных файлов вычисляется `sha256`.
-   `--output` — путь к файлу (по умолчанию `versions/<id>.json`).

Пример результата:

```json
{
    "schema_version": 2,
    "version_id": "demo",
    "comfy": {
        "repo": "https://github.com/comfyanonymous/ComfyUI",
        "ref": "main",
        "commit": "<resolved-sha>"
    },
    "custom_nodes": [
        {
            "name": "ComfyUI-Custom-Scripts",
            "repo": "https://github.com/comfyanonymous/ComfyUI-Custom-Scripts",
            "ref": "main",
            "commit": "<resolved-sha>"
        }
    ],
    "models": [
        {
            "name": "model.safetensors",
            "source": "https://example.com/model.safetensors",
            "target_subdir": "checkpoints",
            "target_path": "checkpoints/model.safetensors",
            "checksum": "sha256:..."
        }
    ],
    "env": {},
    "options": {}
}
```

### Реализация версии (schema_v2)

```bash
# По id (берёт versions/<id>.json)
python3 scripts/realize_version.py --version-id "$COMFY_VERSION_NAME"

# Явный путь к JSON
python3 scripts/realize_version.py --spec versions/$COMFY_VERSION_NAME.json

# dry-run: только показать план
python3 scripts/realize_version.py --version-id "$COMFY_VERSION_NAME" --dry-run

# оффлайн (без git/pip операций)
python3 scripts/realize_version.py --version-id "$COMFY_VERSION_NAME" --offline

# собственные пути
python3 scripts/realize_version.py \
  --version-id "$COMFY_VERSION_NAME" \
  --target /runpod-volume/comfy-$COMFY_VERSION_NAME \
  --models-dir /workspace/models \
  --wheels-dir /workspace/wheels
```

Результат: создаётся кеш `~/.cache/runpod-comfy/resolved/<version_id>.lock.json` (переменная `COMFY_CACHE_ROOT`), готовится `COMFY_HOME` с `.venv`. Ядро и кастом-ноды подтягиваются из общего кеша `<slug>@<commit>`, модели складываются в общий `MODELS_DIR` и линкуются в версию. Рядом генерируется `extra_model_paths.yaml`. Команда `--dry-run` печатает план; `--wheels-dir` включает установку с `--no-index --find-links`.

### Удаление версии

```bash
./scripts/remove_version.sh --target "$HOME/comfy-$COMFY_VERSION_NAME"
```

Опции и безопасность:

-   `--yes` — без подтверждений (non-interactive режим).
-   `--remove-models` — удалить также каталог `models` внутри окружения.
-   `--remove-root` — попытаться удалить корневой каталог окружения после очистки.
-   `--dry-run` — только показать, что будет удалено.

Удаление выполняется только если обнаружен каталог `ComfyUI` или файл-маркер `.comfy_env` (создаётся при клонировании).

### Сборка Docker-образа с handler

```bash
./scripts/build_docker.sh --version "$COMFY_VERSION_NAME" --tag runpod-comfy:local
```

Локальный тест (демо-воркфлоу и заглушка исполнения внутри handler):

```bash
docker run --rm \
  -e COMFY_VERSION_NAME="$COMFY_VERSION_NAME" \
  -e GCS_BUCKET="$GCS_BUCKET" \
  -e GOOGLE_APPLICATION_CREDENTIALS="/path/in/container/key.json" \
  -e GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  runpod-comfy:local --help | cat
```

Запуск с версией и workflow:

```bash
docker run --rm \
  -e COMFY_VERSION_NAME="$COMFY_VERSION_NAME" \
  -e OUTPUT_MODE=gcs \
  runpod-comfy:local \
  --version-id "$COMFY_VERSION_NAME" \
  --workflow /app/workflows/example.json \
  --output gcs | cat
```

### Локальный запуск handler (без Docker)

Handler теперь поддерживает реальное выполнение ComfyUI workflow в headless режиме:

```bash
./scripts/run_handler_local.sh \
  --version-id "$COMFY_VERSION_NAME" \
  --workflow ./workflows/example.json \
  --output base64
```

Новые параметры handler:

-   `--models-dir` — базовая директория для моделей (по умолчанию `$COMFY_HOME/models`)
-   `--output` — режим вывода: `base64` или `gcs` (по умолчанию `gcs`)

Пример с новыми параметрами:

```bash
./scripts/run_handler_local.sh \
  --version-id comfy-comfytest \
  --workflow ./workflows/minimal.json \
  --models-dir "$COMFY_HOME/models" \
  --output base64

```

По умолчанию используется вывод в GCS. Можно явно указать `--output base64` для работы без облака.

### Репродукция и регрессия

Двойная сборка и сравнение SHA/чек-сумм:

```bash
python3 scripts/version.py resolve "$COMFY_VERSION_NAME"
python3 scripts/version.py realize "$COMFY_VERSION_NAME" --dry-run
python3 scripts/version.py test "$COMFY_VERSION_NAME" --workflow ./workflows/example.json --output base64
```

Сохранить и сравнить хэш артефакта воркфлоу:

```bash
# записать эталон
python3 scripts/repro_workflow_hash.py \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --workflow ./workflows/example.json \
  --baseline ./workflows/example.baseline.json \
  --mode record

# сравнить с эталоном
python3 scripts/repro_workflow_hash.py \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --workflow ./workflows/example.json \
  --baseline ./workflows/example.baseline.json \
  --mode compare
```

### Выходные данные

-   `base64` — результат возвращается прямо в stdout/файл.
-   `gcs` — результат загружается в `gs://$GCS_BUCKET/...`, в ответе — ссылка/путь к объекту.

### Диагностика

-   Повторно запустите скрипты с флагом `--verbose` (если предусмотрен).
-   Проверьте корректность `GOOGLE_APPLICATION_CREDENTIALS` и прав на bucket.
-   Сравните текущие зависимости и SHA с содержимым lock-файла.

### RunPod / serverless

-   Базовые инструкции и лучшие практики описаны в `docs/runpod.md`.
-   Ключевые переменные окружения:

    -   `COMFY_HOME` (например `/runpod-volume/comfy`), `MODELS_DIR` (обычно `$COMFY_HOME/models`).
    -   `COMFY_VERSION_NAME` или явный `LOCK_PATH`.
    -   `OUTPUT_MODE` (`gcs` по умолчанию) и GCS-переменные (`GCS_BUCKET`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`/`GCS_PROJECT`, `GCS_PREFIX`, `GCS_RETRIES`, `GCS_RETRY_BASE_SLEEP`, `GCS_PUBLIC`, `GCS_SIGNED_URL_TTL`).

-   Smoke-тест в контейнере:

    ```bash
    echo '{}' > workflows/minimal.json
    python -m rp_handler.main \
      --version-id "${COMFY_VERSION_NAME}" \
      --workflow /app/workflows/minimal.json \
      --output base64 | head -c 80; echo
    ```

    Для GCS:

    ```bash
    python -m rp_handler.main \
      --version-id "${COMFY_VERSION_NAME}" \
      --workflow workflows/minimal.json \
      --output gcs | cat
    ```

### Верификация и скачивание моделей

```bash
python3 scripts/verify_models.py --models-dir "$MODELS_DIR" --verbose
```

Скрипт использует единый кэш моделей (`$COMFY_CACHE_ROOT/models`, либо `COMFY_CACHE_MODELS`). При несовпадении checksum модель докачивается и помещается в целевой каталог, затем создаётся symlink. `--lock` больше не требуется — модели берутся из спецификации версии.

Параметры:

-   `--models-dir DIR` — базовая директория моделей (по умолчанию `$COMFY_HOME/models`).
-   `--overwrite` — перезаписать при несовпадении checksum.
-   `--timeout SEC` — таймаут сетевых загрузок (по умолчанию 120).
-   `--verbose` — подробный вывод.

Поддерживаемые источники `source`:

-   `http(s)`
-   `file:///` и относительные пути
-   `gs://` (требуется `gsutil`)
-   `hf://` (`huggingface://`) — токен `HF_TOKEN` для приватных репозиториев
-   `civitai://` — токен `CIVITAI_TOKEN`

### Пиновка Python-зависимостей

Инструменты lock v1 (`create_version.py`, `pin_requirements.py`) более не используются. Зависимости можно устанавливать вручную через `requirements.txt` или wheel-артефакты, а кеширование реализовано на уровне `pip`.
