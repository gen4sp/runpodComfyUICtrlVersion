## Руководство по использованию

Данный документ описывает, как пользоваться инструментами для управления версиями ComfyUI, локально и в Docker/RunPod.

### Предварительные требования

-   macOS, установленный Docker, Python 3.11+.
-   Доступ к интернету для скачивания зависимостей и моделей (или подготовленные wheel-артефакты и локальные источники).
-   (Опционально) Доступ к Google Cloud Storage для загрузки результатов.

### Переменные окружения

-   `COMFY_HOME` — базовая директория установки ComfyUI (локально или путь volume на RunPod).
-   `MODELS_DIR` — базовая директория моделей (по умолчанию `$COMFY_HOME/models`).
-   `COMFY_VERSION_NAME` — удобное имя версии (используется для поиска lock-файла).
-   `LOCK_PATH` — явный путь к lock-файлу (перебивает `COMFY_VERSION_NAME`).
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

### Создание lock-версии

Сгенерируйте lock-файл, зафиксировав SHA/версии ComfyUI, custom nodes, Python-зависимости и модели:

```bash
python3 scripts/create_version.py --name "$COMFY_VERSION_NAME" \
  --comfy-repo https://github.com/comfyanonymous/ComfyUI \
  --custom-node repo=https://github.com/author/custom-node.git,name=custom-node \
  --requirements ./requirements.txt \
  --models-spec ./models/spec.yml \
  --pretty
```

По умолчанию скрипт ищет пути на основе `COMFY_HOME`:

-   `ComfyUI` по адресу: `$COMFY_HOME` (если это git‑репозиторий; иначе используется `$COMFY_HOME/ComfyUI`, либо можно указать явный `--comfy-path`).
-   `venv` для `pip freeze`: `$COMFY_HOME/.venv` (если не задано `--venv`).
-   базовый каталог моделей: `$COMFY_HOME/models` (используется только для экспансии путей в чек‑суммах).

Ключевые параметры:

-   `--name` — имя версии (попадает в `lockfiles/comfy-<name>.lock.json`).
-   `--comfy-path` — путь к локальному репозиторию ComfyUI (git). Если не указан, берется `$COMFY_HOME/ComfyUI`.
-   `--comfy-repo` — URL репозитория для метаданных (необязательно, если есть git remote `origin`).
-   `--custom-node` — повторы вида `name=...,path=...,repo=...,commit=...`. Можно указывать несколько раз. Локальный `path` позволяет autodiscovery commit/remote.
-   `--venv` — путь к venv; если задан/найден venv, зависимости берутся через `pip freeze`.
-   `--requirements` — альтернативно можно указать pinned `requirements.txt` (используется, если нет venv).
-   `--models-spec` — YAML/JSON со списком моделей. Формат: список объектов или `{ models: [...] }`, где элемент: `{ name, source?, target_path, checksum? }`.
-   `--wheel-url name=url` — можно повторять; подменяет `url` для пакета в Python-секции.
-   `--pretty` — человекочитаемый JSON (иначе компактный, стабильно отсортированный).

Результат: `lockfiles/comfy-$COMFY_VERSION_NAME.lock.json`.

Детерминизм: скрипт не добавляет временных меток; коллекции сортируются по стабильным ключам; повторный запуск при неизменных входных дает идентичный вывод.

### Верификация и скачивание моделей

```bash
python3 scripts/verify_models.py --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --models-dir "$COMFY_HOME/models"
```

Параметры:

-   `--cache-dir PATH` — директория кэша артефактов (по умолчанию: `$COMFY_HOME/.cache/models`).
-   `--overwrite` — перезаписывать целевой файл, если checksum не совпадает и есть `source` в lock-файле.
-   `--timeout SEC` — таймаут сетевых загрузок (по умолчанию 120 сек).
-   `--verbose` — подробный вывод статуса по каждой модели.

Поддерживаемые источники `source` в lock-файле:

-   **http/https** — прямые ссылки на файлы.
-   **file** — локальные пути или `file:///...`.
-   **gs://...** — требуется установленный `gsutil` (Google Cloud SDK).
-   **hf://...** или **huggingface://...** — файлы из репозиториев Hugging Face. Поддерживаются публичные и приватные репозитории (через токен).

Hugging Face источники (`hf://`):

-   Формат URL:

    -   `hf://<org>/<repo>@<rev>/<path/inside/repo>`
    -   `hf://<org>/<repo>/<path/inside/repo>?rev=<rev>`

-   Ревизия `<rev>` по умолчанию `main`.
-   Для приватных репозиториев укажите токен в окружении: `HUGGINGFACE_TOKEN` или `HF_TOKEN`.
-   Примеры:

    ```bash
    # Публичный файл по конкретному коммиту
    hf://stabilityai/stable-diffusion-2-1@<commit-sha>/v1-5-pruned.safetensors

    # С ревизией через query
    hf://runwayml/stable-diffusion-v1-5/v1-5-pruned.safetensors?rev=main

    # Приватный репозиторий (токен из окружения)
    export HUGGINGFACE_TOKEN="hf_..."
    hf://myorg/private-model@v1.0/model.safetensors
    ```

Пример секции `models` в lock-файле с Hugging Face:

```json
{
    "models": [
        {
            "name": "sd15",
            "source": "hf://runwayml/stable-diffusion-v1-5/v1-5-pruned.safetensors?rev=main",
            "target_path": "$MODELS_DIR/checkpoints/sd15.safetensors",
            "checksum": "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        }
    ]
}
```

Подстановка переменных в `target_path`:

-   Поддерживаются `$COMFY_HOME` и `$MODELS_DIR` (последний можно задать флагом `--models-dir`).

Пример восстановления удаленного файла:

```bash
rm "$COMFY_HOME/models/path/to/model.safetensors"
python3 scripts/verify_models.py \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --models-dir "$COMFY_HOME/models" \
  --verbose
```

### Пиновка зависимостей

Перевести гибкий `requirements.txt` в детерминированный список для lock-файла:

```bash
python3 scripts/pin_requirements.py \
  --requirements ./requirements.txt \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --in-place \
  --pretty
```

Оффлайн-пиновка при наличии wheel-артефактов:

```bash
python3 scripts/pin_requirements.py \
  --requirements ./requirements.txt \
  --offline --wheels-dir /path/to/wheels \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --in-place
```

Можно явно задать wheel-URL для отдельных пакетов (перезаписывает auto-URL из freeze):

```bash
python3 scripts/pin_requirements.py \
  --requirements ./requirements.txt \
  --wheel-url torch=https://download.pytorch.org/whl/cpu/torch-...whl \
  --wheel-url torchvision=https://download.pytorch.org/whl/cpu/torchvision-...whl \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json --in-place
```

#### Torch/CUDA через lock-файл

Рекомендуется фиксировать колёса `torch*` (и совместимые пакеты) через `--wheel-url` или заранее в `requirements.txt` с `name @ url`.

Примеры (GPU, CUDA 12.4):

```bash
python3 scripts/pin_requirements.py \
  --requirements ./requirements.txt \
  --wheel-url torch=https://download.pytorch.org/whl/cu124/torch-<ver>-cp311-cp311-linux_x86_64.whl \
  --wheel-url torchvision=https://download.pytorch.org/whl/cu124/torchvision-<ver>-cp311-cp311-linux_x86_64.whl \
  --wheel-url xformers=https://download.pytorch.org/whl/cu124/xformers-<ver>-cp311-cp311-linux_x86_64.whl \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json --in-place --pretty
```

Примеры (CPU):

```bash
python3 scripts/pin_requirements.py \
  --requirements ./requirements.txt \
  --wheel-url torch=https://download.pytorch.org/whl/cpu/torch-<ver>-cp311-cp311-manylinux2014_x86_64.whl \
  --wheel-url torchvision=https://download.pytorch.org/whl/cpu/torchvision-<ver>-cp311-cp311-manylinux2014_x86_64.whl \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json --in-place --pretty
```

Во время применения lock-файла `resolver` установит пакеты точно по URL, обеспечивая воспроизводимость для нужного CUDA/CPU профиля.

### Клонирование версии

Развернуть окружение по lock-файлу в новую директорию:

```bash
./scripts/clone_version.sh --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --target "$HOME/comfy-$COMFY_VERSION_NAME"
```

Опции:

-   `--python PYTHON` — базовый Python для утилит на этапе клонирования.
-   `--skip-models` — пропустить проверку/скачивание моделей.
-   `--offline` — установка зависимостей без индексов (только локальные колёса/кэш pip).
-   `--wheels-dir DIR` — директория с wheel-артефактами (для `--offline`).
-   `--pip-extra-args "..."` — дополнительные аргументы для `pip install`.

Пример оффлайн-клона:

```bash
./scripts/clone_version.sh \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --target /runpod-volume/comfy \
  --offline --wheels-dir /wheels
```

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

Запуск с lock и workflow:

```bash
docker run --rm \
  -e COMFY_VERSION_NAME="$COMFY_VERSION_NAME" \
  -e OUTPUT_MODE=gcs \
  runpod-comfy:local \
  --lock /app/lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --workflow /app/workflows/example.json \
  --output gcs | cat
```

### Локальный запуск handler (без Docker)

```bash
./scripts/run_handler_local.sh \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --workflow ./workflows/example.json \
  --output base64
```

По умолчанию используется вывод в GCS. Можно явно указать `--output base64` для работы без облака.

### Репродукция и регрессия

Двойная сборка и сравнение SHA/чек-сумм:

```bash
python3 scripts/repro_env_compare.py \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --verbose
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
    echo '{}' > /app/workflows/minimal.json
    python -m rp_handler.main \
      --lock "/app/lockfiles/comfy-${COMFY_VERSION_NAME}.lock.json" \
      --workflow /app/workflows/minimal.json \
      --output base64 | head -c 80; echo
    ```

    Для GCS:

    ```bash
    python -m rp_handler.main \
      --lock "/app/lockfiles/comfy-${COMFY_VERSION_NAME}.lock.json" \
      --workflow /app/workflows/minimal.json \
      --output gcs | cat
    ```
