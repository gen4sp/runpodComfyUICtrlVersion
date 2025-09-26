## Smoketest: локальная ручная проверка функционала

Ниже — минимальный набор шагов, чтобы вручную проверить функциональность проекта локально на macOS (или в Linux) без RunPod. Проверяется: создание lock, верификация моделей, запуск handler (base64/GCS), сравнение артефакта с базовой метрикой.

### Предусловия

-   Установлены: Python 3.11+, Docker (необязательно для этого smoketest), Git.
-   В корне проекта: `python -m venv .venv && source .venv/bin/activate && pip install -U pip pytest`.
-   По необходимости: `pip install google-cloud-storage` (если хотите проверить вывод в GCS).

### 1) Подготовка рабочего каталога

1. Создайте рабочую директорию для Comfy (локально):
    - `export COMFY_HOME="$(pwd)/comfy"`
    - `mkdir -p "$COMFY_HOME/ComfyUI" "$COMFY_HOME/models"`
2. Создайте пример requirements (опционально):
    - `echo "requests==2.32.3" > requirements.txt`

### 2) Создание lock-файла

1. Минимальный lock без моделей:
    - `python scripts/version.py create local --repo https://github.com/comfyanonymous/ComfyUI@main`
    - Ожидаемый вывод: путь к `lockfiles/comfy-local.lock.json`. Файл должен существовать и содержать базовые секции.
2. (Опционально) Добавить python-зависимости из `requirements.txt`:
    - `python scripts/version.py create local-req --repo https://github.com/comfyanonymous/ComfyUI@main --models models/demo.json`

### 3) Верификация моделей (локально без скачиваний)

1. Создайте тестовый lock с моделями (пример):
    - Создайте файл `lockfiles/comfy-models.lock.json` со структурой:

```json
{
    "models": [
        {
            "name": "dummy",
            "source": null,
            "target_path": "$MODELS_DIR/dummy.bin",
            "checksum": null
        }
    ]
}
```

2. Запустите верификацию:
    - `python scripts/verify_models.py --lock lockfiles/comfy-models.lock.json --models-dir "$COMFY_HOME/models" --verbose`
    - Ожидаемое: файл отсутствует → статус ok или сообщение, что модель отсутствует (по коду возврата 0, если нет ошибок валидации).

Примечание: чтобы протестировать скачивание, укажите `source` как `file:///…` на локальный файл и задайте `checksum`.

### 4) Запуск handler в режиме base64

1. Создайте простой workflow JSON:
    - `echo '{"graph": {}}' > workflow.json`
2. Запустите handler (используется «заглушка» выполнения):
    - `python -m rp_handler.main --lock lockfiles/comfy-local.lock.json --workflow workflow.json --output base64 --verbose`
    - Ожидаемое: в stdout печатается base64-строка. Декодируема в байты содержимого `workflow.json`.

### 5) Сравнение артефакта с базовой метрикой

1. Запись базовой метрики:
    - `python scripts/repro_workflow_hash.py --lock lockfiles/comfy-local.lock.json --workflow workflow.json --baseline baselines/wf.json --mode record`
2. Сравнение:
    - `python scripts/repro_workflow_hash.py --lock lockfiles/comfy-local.lock.json --workflow workflow.json --baseline baselines/wf.json --mode compare`
    - Ожидаемое: вывод «Artifact matches baseline», код возврата 0.

### 6) Запуск handler в режиме GCS (опционально)

1. Подготовьте переменные окружения:
    - `export GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/sa.json`
    - `export GOOGLE_CLOUD_PROJECT=<project_id>`
    - `export GCS_BUCKET=<bucket_name>`
    - (опционально) `export GCS_PREFIX=comfy/outputs` `export GCS_PUBLIC=1` `export GCS_SIGNED_URL_TTL=60`
2. Запуск:
    - `python -m rp_handler.main --lock lockfiles/comfy-local.lock.json --workflow workflow.json --output gcs --gcs-bucket "$GCS_BUCKET" --gcs-prefix "$GCS_PREFIX" --verbose`
    - Ожидаемое: в stdout печатается `gs://…` ссылка. В логах может отображаться signed URL (если включено).

### 7) Быстрый прогон автотестов

-   `pytest -q`
-   Ожидаемое: все тесты проходят локально без внешних сетевых вызовов.

### Троблшутинг

-   Ошибка GCS импорта: установите `pip install google-cloud-storage` или используйте режим `--output base64`.
-   Отсутствуют права на bucket: отключите проверку `export GCS_VALIDATE=0` или настройте IAM.
-   Путь к COMFY_HOME: экспортируйте `COMFY_HOME` перед шагами, чтобы не использовались дефолтные пути.
