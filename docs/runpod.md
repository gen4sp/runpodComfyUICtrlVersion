## RunPod: Pods (volume) и Serverless — руководство

### Обзор

-   **Цель**: запуск ComfyUI по спецификации `versions/<id>.json` в окружениях RunPod.
-   **Режимы**:
    -   Pods с подключённым volume (персистентное хранилище для моделей/версий).
    -   Serverless (холодный старт, рекомендуется заранее запекать зависимости в образ).

### Подготовка образа (serverless-only)

```bash
./scripts/build_docker.sh --tag runpod-comfy:local
./scripts/build_docker.sh --tag gen4sp/runpod-pytorch-serverless:v13
# или вручную, чтобы гарантированно подтянуть свежие файлы entrypoint:
docker build --pull --no-cache -t runpod-comfy:local -f docker/Dockerfile .
# Загрузите образ в свой реестр (GHCR/AR/ECR/Docker Hub), если требуется.
```

Переменные окружения:

-   `COMFY_HOME` (по умолчанию `/runpod-volume/ComfyUI` внутри контейнера) — корень окружения версии.
-   `MODELS_DIR` (по умолчанию `$COMFY_HOME/models`) — каталог моделей; на Pod переопределите на `/runpod-volume/cache/models` или собственный путь внутри volume.
-   `OUTPUT_MODE` — `gcs` (по умолчанию) или `base64`.
-   GCS: `GCS_BUCKET` (обязателен для `gcs`), `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`/`GCS_PROJECT`,
    `GCS_PREFIX` (по умолчанию `comfy/outputs`), `GCS_RETRIES` (3), `GCS_RETRY_BASE_SLEEP` (0.5), `GCS_PUBLIC` (false), `GCS_SIGNED_URL_TTL` (0), `GCS_VALIDATE` (true).

Примечание: режим Pods (volume) предполагает, что `COMFY_HOME` указывает на `/runpod-volume/builds/comfy-<id>`, а кеши — на `/runpod-volume/cache/runpod-comfy`.

### Serverless

-   Образ включает тонкий адаптер: `rp_handler.serverless`.
-   Запуск: первый аргумент `serverless` или переменная `RUNPOD_SERVERLESS=1`.

Схема payload (RunPod job `input`):

```json
{
    "version_id": "wan22-fast",
    "workflow": { "nodes": {} },
    "workflow_url": "https://.../workflow.json",
    "input_images": {
        "img1.png": "https://example.com/image1.jpg",
        "img2.png": "https://storage.googleapis.com/bucket/image2.png"
    },
    "output_mode": "gcs",
    "gcs_bucket": "<bucket>",
    "gcs_prefix": "comfy/outputs",
    "models_dir": "/runpod-volume/models",
    "verbose": false
}
```

-   `version_id` — обязательно; должен соответствовать файлу `versions/<id>.json` (файл должен быть смонтирован или включён в образ произвольно; образ общий, не привязан к версии).
-   `workflow` — объект JSON или строка JSON. Альтернатива: `workflow_url` (HTTP/HTTPS URL на JSON).
-   `input_images` — необязательно; словарь `{filename: url}` для загрузки входных изображений. Изображения будут скачаны в `{COMFY_HOME}/input/` перед запуском workflow. В workflow используйте узел `LoadImage` с указанными именами файлов.
-   `output_mode` — `gcs` (по умолчанию) или `base64`.
-   Для `gcs`: укажите `GCS_BUCKET`/`gcs_bucket` и креды (`GOOGLE_APPLICATION_CREDENTIALS` указывает на путь к JSON в контейнере).
-   `models_dir` — необязательно; по умолчанию `/runpod-volume/models`.

Запуск образа в RunPod Serverless:

1. Соберите и (при необходимости) загрузите образ в реестр (используйте уникальный тег, чтобы RunPod не кешировал старый entrypoint):

```bash
./scripts/build_docker.sh --tag gen4sp/runpod-pytorch-serverless:v13
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

3. Отправка задания (примеры тел запроса):

**Text-to-Image (без входных изображений):**

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

**Image-to-Image (с входными изображениями):**

```json
{
    "input": {
        "version_id": "wan22-fast",
        "workflow_url": "https://example.com/workflows/wan22-i2i.json",
        "input_images": {
            "img1.png": "https://storage.googleapis.com/my-bucket/source-image.jpg",
            "img2.png": "https://example.com/style-reference.png"
        },
        "output_mode": "gcs",
        "gcs_bucket": "<bucket>"
    }
}
```

**С inline workflow и изображениями:**

```json
{
    "input": {
        "version_id": "wan22-fast",
        "workflow": {
            "1": {"inputs": {"image": "input.jpg"}, "class_type": "LoadImage"},
            "2": {...}
        },
        "input_images": {
            "input.jpg": "https://example.com/my-image.jpg"
        },
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

### Работа с входными изображениями

#### Передача изображений через URLs

Поддерживаются два формата передачи изображений:

**Формат 1: `input_images` (словарь)**

```json
{
    "input": {
        "version_id": "wan22-fast",
        "workflow": {...},
        "input_images": {
            "img1.png": "https://example.com/image.jpg",
            "style.png": "https://storage.googleapis.com/bucket/style.png"
        }
    }
}
```

**Формат 2: `images` (массив)**

```json
{
    "input": {
        "version_id": "wan22-fast",
        "workflow": {...},
        "images": [
            {
                "name": "img1.png",
                "image": "https://example.com/image.jpg"
            },
            {
                "name": "style.png",
                "image": "https://storage.googleapis.com/bucket/style.png"
            }
        ]
    }
}
```

**Требования к URL:**

-   Изображения должны быть доступны по HTTP/HTTPS без аутентификации или с bearer token в URL
-   Поддерживаются форматы: JPG, PNG, WebP, GIF и другие форматы, поддерживаемые PIL
-   Имена файлов должны совпадать с теми, что используются в workflow узлах `LoadImage`
-   Оба формата можно использовать одновременно (файлы из обоих источников будут загружены)

**Best practices:**

1. Используйте публичные URL или signed URLs для облачных хранилищ (GCS, S3)
2. Для GCS используйте signed URLs с ограниченным временем жизни
3. Оптимизируйте размер изображений перед загрузкой (resize/compress), чтобы ускорить передачу
4. Имена файлов могут повторяться между запросами — система автоматически создаст уникальные имена

**Автоматическое управление файлами:**

Начиная с последней версии, система автоматически управляет входными файлами:

1. **Уникальные имена файлов**: Каждый входной файл автоматически получает уникальное имя на основе `requestId`:
   - Формат: `{requestId}_{random8chars}_{originalname}.ext`
   - Пример: `req12345abc_def67890_img1.png`
   - Это предотвращает конфликты при одновременной обработке нескольких запросов с одинаковыми именами файлов

2. **Автоматическая замена имен в workflow**: Система автоматически находит и заменяет имена файлов в workflow JSON:
   - Поддерживаются оба формата workflow (API и UI)
   - Обрабатываются ноды: `LoadImage`, `VHS_LoadVideo`, `LoadImageMask`
   - Пользователю не нужно вручную модифицировать workflow

3. **Автоматическая очистка файлов**: После завершения обработки и загрузки результатов в GCS:
   - Все входные файлы текущего запроса удаляются автоматически
   - Файлы других запросов не затрагиваются
   - Экономится дисковое пространство в serverless окружении

4. **Трассировка в GCS**: Выходные файлы в GCS также содержат `requestId` в имени:
   - Формат: `{prefix}/{requestId}_{timestamp}-{uuid}.ext`
   - Упрощает отладку и мониторинг

**Преимущества:**

- ✅ Можно использовать одни и те же имена файлов (`img1.png`, `img2.png`) во всех запросах
- ✅ Нет конфликтов при параллельной обработке запросов
- ✅ Автоматическая изоляция файлов между запросами
- ✅ Не требуется изменять workflow JSON вручную
- ✅ Автоматическое освобождение дискового пространства

**Пример с GCS signed URL:**

```bash
# Создание signed URL (действителен 1 час)
gsutil signurl -d 1h /path/to/service-account.json gs://bucket/image.jpg
```

**В workflow:**

```json
{
    "1": {
        "inputs": {
            "image": "img1.png"
        },
        "class_type": "LoadImage"
    }
}
```

### Совместимость путей и прав

-   Для Pods используйте `/runpod-volume` как базу: окружение размещайте в `/runpod-volume/builds/comfy-<id>`, кеш — в `/runpod-volume/cache/runpod-comfy`, модели — в `/runpod-volume/models` или другом каталоге.
-   Внутри образа дефолты: `/runpod-volume/ComfyUI` и `/runpod-volume/models`. Их следует переопределять переменными окружения, если используется volume.
-   Все скрипты и handler работают в non-interactive режиме; подходят для serverless.

### Диагностика

-   Запускайте с `--verbose`, проверяйте валидность `GOOGLE_APPLICATION_CREDENTIALS` и прав на `GCS_BUCKET`.
-   При ошибках загрузки в GCS можно временно переключиться на `--output base64` для локальной проверки.

#### Ошибка "context deadline exceeded" при создании контейнера

**Симптом:**

```
worker is ready
create container gen4sp/runpod-pytorch-serverless:v12
error creating container: context deadline exceeded
```

**Причина:** Контейнер пытается стартовать, но volume не успевает примонтироваться, что вызывает timeout.

**Решение:**

1. Entrypoint теперь ждёт до 60 секунд монтирования volume перед запуском
2. Пересоберите образ с **новым тегом**:
    ```bash
    docker build -t gen4sp/runpod-pytorch-serverless:v13 -f docker/Dockerfile .
    docker push gen4sp/runpod-pytorch-serverless:v13
    ```
3. Обновите Serverless Template с новым тегом образа
4. Убедитесь что Network Volume правильно подключён к endpoint:
    - Storage → Network Volumes → выберите volume
    - Serverless Template → Advanced → Network Volume → выберите volume
    - Mount Path должен быть `/runpod-volume`
5. Убедитесь что код размещён на volume: `/runpod-volume/runpodComfyUICtrlVersion/{scripts,rp_handler,versions,models,nodes}`
