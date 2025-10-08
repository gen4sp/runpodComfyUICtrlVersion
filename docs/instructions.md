## Руководство по использованию

Комплект утилит ориентирован на единую схему `versions/<id>.json`. Все операции выполняются через `python3 scripts/version.py ...`.

### Предварительные требования

-   Python 3.11+
-   Git
-   Docker (если планируется проверять handler в контейнере)
-   Доступ к интернету для первичного скачивания ядра/нод/моделей

### Переменные окружения

| Переменная                  | Назначение                                                                                                                                                                                |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `COMFY_HOME`                | Путь развёрнутой версии. Если переменная не задана — внутри образа используется `/runpod-volume/ComfyUI`, локально `~/comfy-<id>`, на RunPod volume — `/runpod-volume/builds/comfy-<id>`. |
| `MODELS_DIR`                | Путь к моделям. Если не указан — используется общий кеш `COMFY_CACHE_ROOT/models`.                                                                                                        |
| `COMFY_CACHE_ROOT`          | Базовый каталог кеша (по умолчанию `/runpod-volume/cache/runpod-comfy`, без volume — `~/.cache/runpod-comfy`, в контейнере без volume — `/runpod-volume/cache/runpod-comfy`).             |
| `COMFY_OFFLINE`             | Если `true`, resolver/realizer не выполняют сетевые операции (коммиты и модели должны быть уже в кеше).                                                                                   |
| `OUTPUT_MODE`               | Режим вывода handler (`base64` или `gcs`, по умолчанию `gcs`).                                                                                                                            |
| `GCS_*`                     | Настройки для выгрузки результатов в Google Cloud Storage.                                                                                                                                |
| `HF_TOKEN`, `CIVITAI_TOKEN` | Токены для скачивания моделей.                                                                                                                                                            |

### Структура спецификации версии

Файл `versions/<id>.json` содержит:

-   `schema_version`: версия схемы (2)
-   `version_id`: идентификатор версии
-   `comfy`: репозиторий и коммит ядра ComfyUI
-   `custom_nodes`: список кастом-нод с репозиториями и коммитами
-   `models`: модели с источниками и путями назначения
-   `python_packages` (опционально): список дополнительных Python пакетов для установки
-   `env`: переменные окружения (опционально)
-   `options`: флаги поведения (`offline`, `skip_models`)

Пример с `python_packages`:

```json
{
  "schema_version": 2,
  "version_id": "my-version",
  "comfy": { "repo": "https://github.com/comfyanonymous/ComfyUI", "ref": "master" },
  "custom_nodes": [...],
  "models": [...],
  "python_packages": ["sageattention", "onnx>=1.14", "onnxruntime-gpu"],
  "env": {},
  "options": {}
}
```

Пакеты из `python_packages` устанавливаются после зависимостей кастом-нод, но перед подготовкой моделей. Можно указывать версии в формате pip: `package==1.0.0`, `package>=2.0`, `package`.

### Создание версии

```bash
python3 scripts/version.py create wan-demo \
  --repo https://github.com/comfyanonymous/ComfyUI@master \
  --nodes nodes.json \
  --models models.json
```

-   `--nodes` и `--models` принимают либо JSON-объекты, либо пути к JSON/YAML файлам.
-   Если `--models-root` указывает на локальный каталог, флаг `--auto-checksum` автоматически проставит `sha256`.
-   Готовая спецификация сохраняется в `versions/wan-demo.json` (путь можно переопределить `--output`).
-   Для добавления дополнительных Python пакетов отредактируйте сгенерированный JSON, добавив поле `python_packages`.

### Проверка спецификации

```bash
python3 scripts/version.py validate wan-demo
```

Команда резолвит SHA, проверяет корректность полей и сохраняет lock-файл кеша `resolved/wan-demo.lock.json`. Добавьте `--offline`, если коммиты уже есть в кеше.

### Развёртывание окружения

```bash
COMFY_HOME=~/comfy-wan python3 scripts/version.py realize wan-demo
```

По умолчанию целевой путь вычисляется автоматически (внутри контейнера — `/runpod-volume/ComfyUI`). Для Pod с volume укажите `COMFY_HOME=/runpod-volume/builds/comfy-wан` или `--target /runpod-volume/builds/comfy-wан`. Для оффлайн-режима добавьте `--offline`. Опция `--wheels-dir` позволяет указывать каталог с wheel-ами для `pip install` без доступа к интернету.

### Запуск UI

```bash
python3 scripts/version.py run-ui wan-demo --port 9000 --extra-args -- --no-auto-launch
```

-   `--host` и `--port` управляют HTTP интерфейсом (по умолчанию `0.0.0.0:8188`).
-   Дополнительные параметры после `--extra-args --` передаются напрямую `ComfyUI/main.py`.
-   Переменные `COMFY_HOME` и `MODELS_DIR` выставляются автоматически согласно реализованной версии.

### Запуск handler

```bash
python3 scripts/version.py run-handler wan-demo \
  --workflow workflows/demo.json \
  --output base64 --out-file artifacts/output.b64
```

-   Handler повторно использует кеш и окружение. Путь к workflow должен указывать на JSON граф.
-   Для вывода в GCS задайте `--output gcs`, `--gcs-bucket`, `--gcs-prefix` и соответствующие переменные окружения.
-   Флаг `--offline` временно выставит `COMFY_OFFLINE=1` для запуска.

### Управление версиями

```bash
# Клонировать спецификацию
python3 scripts/version.py clone wan-demo wan-test

# Удалить развёрнутую версию и lock
python3 scripts/version.py delete wan-demo

# Удалить также исходную спецификацию
python3 scripts/version.py delete wan-demo --remove-spec
```

### Docker / RunPod

1. Соберите образ:

    ```bash
    ./scripts/build_docker.sh --version wan-demo --tag runpod-comfy:wan-demo
    ```

2. Запустите handler в контейнере:

    ```bash
    docker run --rm \
      -e COMFY_VERSION_NAME=wan-demo \
      -e OUTPUT_MODE=base64 \
      -v "$PWD/workflows":/app/workflows \
      runpod-comfy:wan-demo \
      --version-id wan-demo \
      --workflow /app/workflows/demo.json \
      --output base64
    ```

3. Для RunPod Pods используйте `COMFY_HOME=/runpod-volume/builds/comfy-<id>` и выполните `python3 scripts/version.py realize <id>` один раз на volume. Дальнейшие запуски UI/handler используют готовое окружение и кеши.

### Проверка моделей отдельно

Для ручной проверки и скачивания моделей можно использовать `scripts/verify_models.py` с указанием каталога моделей и того же кеша. Скрипт принимает `--lock` JSON (сгенерированный `save_resolved_lock`) или напрямую список моделей. См. комментарии в файле для детальной информации.
