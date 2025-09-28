## RunPod: Pods (volume) и Serverless — руководство

### Обзор

-   **Цель**: запуск ComfyUI по спецификации `versions/<id>.json` в окружениях RunPod.
-   **Режимы**:
    -   Pods с подключённым volume (персистентное хранилище для моделей/версий).
    -   Serverless (холодный старт, рекомендуется заранее запекать зависимости в образ).

### Подготовка образа (serverless-only)

```bash
./scripts/build_docker.sh --tag runpod-comfy:local
# или вручную, чтобы гарантированно подтянуть свежие файлы entrypoint:
docker build --pull --no-cache -t runpod-comfy:local -f docker/Dockerfile .
# Загрузите образ в свой реестр (GHCR/AR/ECR/Docker Hub), если требуется.
```

Переменные окружения:

-   `COMFY_HOME` (по умолчанию `/workspace/ComfyUI` внутри контейнера) — корень окружения версии.
-   `MODELS_DIR` (по умолчанию `$COMFY_HOME/models`) — каталог моделей; на Pod переопределите на `/runpod-volume/...`.
-   `OUTPUT_MODE` — `gcs` (по умолчанию) или `base64`.
-   GCS: `GCS_BUCKET` (обязателен для `gcs`), `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`/`GCS_PROJECT`,
    `GCS_PREFIX` (по умолчанию `comfy/outputs`), `GCS_RETRIES` (3), `GCS_RETRY_BASE_SLEEP` (0.5), `GCS_PUBLIC` (false), `GCS_SIGNED_URL_TTL` (0), `GCS_VALIDATE` (true).

Примечание: режим Pods (volume) не рассматривается — образ предназначен для RunPod Serverless.

### Serverless

-   Образ включает тонкий адаптер: `rp_handler.serverless`.
-   Запуск: первый аргумент `serverless` или переменная `RUNPOD_SERVERLESS=1`.

Схема payload (RunPod job `input`):

```json
{
    "version_id": "wan22-fast",
    "workflow": { "nodes": {} },
    "workflow_url": "https://.../workflow.json",
    "output_mode": "gcs",
    "gcs_bucket": "<bucket>",
    "gcs_prefix": "comfy/outputs",
    "models_dir": "/workspace/models",
    "verbose": false
}
```

-   `version_id` — обязательно; должен соответствовать файлу `versions/<id>.json` (файл должен быть смонтирован или включён в образ произвольно; образ общий, не привязан к версии).
-   `workflow` — объект JSON или строка JSON. Альтернатива: `workflow_url` (HTTP/HTTPS URL на JSON).
-   `output_mode` — `gcs` (по умолчанию) или `base64`.
-   Для `gcs`: укажите `GCS_BUCKET`/`gcs_bucket` и креды (`GOOGLE_APPLICATION_CREDENTIALS` указывает на путь к JSON в контейнере).
-   `models_dir` — необязательно; по умолчанию `/workspace/models`.

Запуск образа в RunPod Serverless:

1. Соберите и (при необходимости) загрузите образ в реестр (используйте уникальный тег, чтобы RunPod не кешировал старый entrypoint):

```bash
./scripts/build_docker.sh --tag <registry>/<image>:<tag>
# docker push <registry>/<image>:<tag>
```

2. В шаблоне Serverless укажите:

    - Image: `<registry>/<image>:<tag>`
    - Command можно оставить пустым; Args — пусто или `serverless` (по умолчанию entrypoint всё равно запустит serverless).
    - Env:
        - `OUTPUT_MODE=gcs` (или `base64`)
        - `GCS_BUCKET=<bucket>`
        - `GOOGLE_APPLICATION_CREDENTIALS=/opt/creds/sa.json` (и положите файл в образ/секрет)
        - опционально `GCS_PREFIX`, `GCS_PUBLIC`, `GCS_SIGNED_URL_TTL`

    Примечание: если нужно запустить CLI-handler, передайте `cli` в Args.

3. Отправка задания (пример тела запроса):

```json
{
    "input": {
        "version_id": "wan22-fast",
        "workflow_url": "https://example.com/workflows/wan22-fast.json",
        "output_mode": "gcs",
        "gcs_bucket": "<bucket>"
    }
}
```

Возвращаемое значение:

-   `output_mode=gcs`: `{ "gcs_url": "gs://bucket/key", "size": <bytes>, ... }`
-   `output_mode=base64`: `{ "base64": "...", "size": <bytes> }`

Оптимизация холодного старта:

-   Чтобы избежать переустановки Python-пакетов на каждом инстансе, запекайте зависимости напрямую (создайте `requirements.txt` и `pip install` на build-стадии).
-   Модели держите на volume/в GCS. `verify_models.py` докачает недостающее в единый кэш `COMFY_CACHE_ROOT/models`.

### Совместимость путей и прав

-   Для Pods используйте `/runpod-volume` как базу для `COMFY_HOME` и моделей.
-   Внутри образа дефолты: `/workspace/ComfyUI` и `/workspace/models`. Их следует переопределять переменными окружения, если используется volume.
-   Все скрипты и handler работают в non-interactive режиме; подходят для serverless.

### Диагностика

-   Запускайте с `--verbose`, проверяйте валидность `GOOGLE_APPLICATION_CREDENTIALS` и прав на `GCS_BUCKET`.
-   При ошибках загрузки в GCS можно временно переключиться на `--output base64` для локальной проверки.
