## RunPod: Pods (volume) и Serverless — руководство

### Обзор

-   **Цель**: запуск ComfyUI по спецификации `versions/<id>.json` в окружениях RunPod.
-   **Режимы**:
    -   Pods с подключённым volume (персистентное хранилище для моделей/версий).
    -   Serverless (холодный старт, рекомендуется заранее запекать зависимости в образ).

### Подготовка образа

```bash
./scripts/build_docker.sh --version "$COMFY_VERSION_NAME" --tag runpod-comfy:local
# Загрузите образ в свой реестр (GHCR/AR/ECR/Docker Hub), если требуется.
```

Переменные, которые использует handler:

-   `COMFY_HOME` (по умолчанию `/workspace/ComfyUI` внутри контейнера) — корень окружения версии.
-   `MODELS_DIR` (по умолчанию `$COMFY_HOME/models`) — каталог моделей; на Pod переопределите на `/runpod-volume/...`.
-   `COMFY_VERSION_NAME` — имя версии; по нему ищется спека `versions/<id>.json`.
-   `OUTPUT_MODE` — `gcs` (по умолчанию) или `base64`.
-   GCS: `GCS_BUCKET` (обязателен для `gcs`), `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`/`GCS_PROJECT`,
    `GCS_PREFIX` (по умолчанию `comfy/outputs`), `GCS_RETRIES` (3), `GCS_RETRY_BASE_SLEEP` (0.5), `GCS_PUBLIC` (false), `GCS_SIGNED_URL_TTL` (0), `GCS_VALIDATE` (true).

### Pods (volume)

1. Подготовьте Pod с volume, смонтированным в `/runpod-volume`.

2. Рекомендуемые переменные окружения Pod (пример с volume `/runpod-volume`):

```text
COMFY_HOME=/runpod-volume/comfy
MODELS_DIR=/runpod-volume/comfy/models
COMFY_VERSION_NAME=<ваша_версия>
OUTPUT_MODE=gcs
GCS_BUCKET=<bucket>
GOOGLE_APPLICATION_CREDENTIALS=/opt/creds/sa.json   # путь внутри контейнера
GOOGLE_CLOUD_PROJECT=<gcp-project>
GCS_PREFIX=comfy/outputs
GCS_RETRIES=3
GCS_RETRY_BASE_SLEEP=0.5
GCS_PUBLIC=false
GCS_SIGNED_URL_TTL=0
GCS_VALIDATE=true
```

3. Права на volume: по умолчанию контейнер запускается от root, запись в `/runpod-volume` разрешена. Проверка:

```bash
ls -ld /runpod-volume
mkdir -p /runpod-volume/comfy/models
```

4. Размещение спеки версии: включите `versions/<id>.json` в образ (`/app/versions`) или смонтируйте её.
   Для автоматической развёртки окружения на volume используйте `scripts/version.py`:

```bash
# Пример быстрой развёртки версии на volume
python3 /app/scripts/version.py realize "$COMFY_VERSION_NAME"
# или с явным путём
python3 /app/scripts/version.py realize "$COMFY_VERSION_NAME" --target /runpod-volume/comfy-$COMFY_VERSION_NAME
```

5. Smoke-тест (минимальный воркфлоу):

```bash
echo '{}' > /tmp/minimal.json
python -m rp_handler.main \
  --version-id "${COMFY_VERSION_NAME}" \
  --workflow /tmp/minimal.json \
  --output base64 | head -c 80; echo
# Ожидается base64-строка (контент заглушки/воркфлоу).
```

При `--output gcs` команда выведет `gs://bucket/key` — ссылку на объект.

### Serverless

-   Базовый образ и handler рассчитаны на **CLI-вызов** (`python -m rp_handler.main ...`).
-   Для Serverless рекомендуется тонкий адаптер, который маппит входной JSON RunPod job → аргументы CLI.
    На данном этапе можно:
    -   Задать команду запуска контейнера с нужными аргументами (`CMD`/`Args`) либо
    -   Подготовить собственный мини-скрипт-обёртку в образе.

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
