## RunPod: Pods (volume) и Serverless — руководство

### Обзор

-   **Цель**: запуск ComfyUI-процессов по зафиксированной версии (lock) в окружениях RunPod.
-   **Режимы**:
    -   Pods с подключённым volume (персистентное хранилище для моделей/версий).
    -   Serverless (холодный старт, рекомендуется заранее запекать зависимости в образ).

### Подготовка образа

```bash
./scripts/build_docker.sh --version "$COMFY_VERSION_NAME" --tag runpod-comfy:local
# Загрузите образ в свой реестр (GHCR/AR/ECR/Docker Hub), если требуется.
```

Переменные, которые использует handler:

-   `COMFY_HOME` (по умолчанию `/opt/comfy`) — корень окружения версии.
-   `MODELS_DIR` (по умолчанию `$COMFY_HOME/models`) — каталог моделей.
-   `COMFY_VERSION_NAME` — имя версии; по нему в образе ищется lock-файл: `/app/lockfiles/comfy-<name>.lock.json`.
-   `LOCK_PATH` — явный путь к lock-файлу (перебивает `COMFY_VERSION_NAME`).
-   `OUTPUT_MODE` — `gcs` (по умолчанию) или `base64`.
-   GCS: `GCS_BUCKET` (обязателен для `gcs`), `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`/`GCS_PROJECT`,
    `GCS_PREFIX` (по умолчанию `comfy/outputs`), `GCS_RETRIES` (3), `GCS_RETRY_BASE_SLEEP` (0.5), `GCS_PUBLIC` (false), `GCS_SIGNED_URL_TTL` (0), `GCS_VALIDATE` (true).

### Pods (volume)

1. Подготовьте Pod с volume, смонтированным в `/runpod-volume`.

2. Рекомендуемые переменные окружения Pod:

```text
COMFY_HOME=/runpod-volume/comfy
MODELS_DIR=/runpod-volume/comfy/models
COMFY_VERSION_NAME=<ваша_версия>
OUTPUT_MODE=gcs
GCS_BUCKET=<bucket>
GOOGLE_APPLICATION_CREDENTIALS=/workspace/sa.json   # путь внутри контейнера
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

4. Размещение lock-файла: либо включите его в образ (копируется в `/app/lockfiles` при сборке), либо задайте явный путь через `LOCK_PATH`.

5. Smoke-тест (минимальный воркфлоу):

```bash
echo '{}' > /app/workflows/minimal.json
python -m rp_handler.main \
  --lock "/app/lockfiles/comfy-${COMFY_VERSION_NAME}.lock.json" \
  --workflow /app/workflows/minimal.json \
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

-   Чтобы избежать установки Python-пакетов на каждом инстансе, запекайте pinned зависимости из lock-файла прямо в образ
    (например, отдельным build-этапом, который генерирует `requirements.txt` из `python.packages` секции lock и делает `pip install`).
-   Модели держите на volume/в кэше GCS; `verify_models.py` докачает недостающее.

### Совместимость путей и прав

-   Для Pods используйте `/runpod-volume` как базу для `COMFY_HOME` и моделей.
-   Внутри образа дефолты: `/opt/comfy` и `/opt/comfy/models`. Их следует переопределять переменными окружения, если используется volume.
-   Все скрипты и handler работают в non-interactive режиме; подходят для serverless.

### Диагностика

-   Запускайте с `--verbose`, проверяйте валидность `GOOGLE_APPLICATION_CREDENTIALS` и прав на `GCS_BUCKET`.
-   При ошибках загрузки в GCS можно временно переключиться на `--output base64` для локальной проверки.
