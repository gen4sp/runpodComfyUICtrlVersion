## Технический обзор и структура проекта

Цель: обеспечить воспроизводимое управление версиями ComfyUI для RunPod (volume/serverless) и локальных запусков, с фиксацией зависимостей/узлов по SHA через спецификации `versions/<id>.json` (schema v2) и удобными сценариями сборки и тестирования.

### Общая структура каталогов

Предлагаемая структура (часть папок появится по мере реализации скриптов):

-   `scripts/`
    -   Скрипты автоматизации: инициализация, создание/клонирование/удаление версии, сборка образов, локальные проверки.
-   `versions/`
    -   Материалы конкретных версий: `versions/<id>.json` (schema v2 спецификация), артефакты, документация.
-   `docker/`
    -   Dockerfile(ы), entrypoint, runtime-конфиги, handler (серверless/CLI входная точка).
-   `workflows/`
    -   Шаблоны и примеры воркфлоу ComfyUI (JSON/graph), используемые handler.
-   `models/`
    -   Описание источников моделей (не сами модели). Скачивание выполняется скриптами согласно lock-файлам.
-   `docs/`
    -   Дополнительная документация, диаграммы, примеры конфигов.

Корневые файлы:

-   `readme.md` — обзор, быстрый старт, ссылки.
-   `tech.md` — этот документ, техническое устройство.
-   `todo.md` — пошаговый план реализации и тестирования.
-   `instructions.md` — руководство пользователя.

### Ключевые артефакты

-   Спецификация версии (`versions/<id>.json`, schema v2):

    -   `comfy`: { `repo`, `ref?`, `commit` }
    -   `custom_nodes`: [{ `name?`, `repo`, `ref?`, `commit` }]
    -   `models`: [{ `source`, `target_subdir?`, `target_path?`, `name?`, `checksum?` }]
    -   `env`: дополнительные переменные окружения (опционально)
    -   `options`: `{ offline?, skip_models? }`

-   Resolved-lock (`/runpod-volume/cache/runpod-comfy/resolved/<id>.lock.json`) создаётся автоматически.

-   Handler:
    -   Принимает: путь/описание воркфлоу и `--version-id/--spec` (без lock-файла), параметры вывода.
    -   Возвращает: base64-результат или ссылку в GCS.
    -   Встраивается в Docker и может работать локально.

### Скрипты

В каталоге `scripts/` утилиты:

-   `init_comfyui.sh` — развертывание ComfyUI, базовая структура, создание `venv`.
-   `version.py` — CLI высокого уровня (`create`, `validate`, `resolve`, `realize`, `run-ui`, `run-handler`, `clone`, `delete`).
-   `build_docker.sh` — сборка Docker-образа с handler.
-   `verify_models.py` — проверка наличия/хэшей моделей из speс (`versions/<id>.json`), скачивание недостающих.

#### `verify_models.py` (детали)

-   Алгоритмы checksum: `sha256` (по умолчанию), поддерживается также `md5`. Формат: `algo:hex`.
-   Экспансия путей: переменные `$COMFY_HOME` и `$MODELS_DIR` в `target_path`.
-   Источники загрузки: `http(s)`, `file`/локальный путь, `gs://...` (через `gsutil`).
-   Кэш артефактов: по умолчанию в `$COMFY_HOME/.cache/models/<algo>/<HH>/<hex>/blob`.
-   Атомарная запись: скачивание во временный файл и `os.replace` в целевой путь.
-   Поведение при несовпадении checksum: без `--overwrite` — ошибка; с `--overwrite` — повторная загрузка/восстановление из кэша.

### Docker и handler

-   `docker/Dockerfile`

    -   Базовый образ с Python, системными зависимостями для ComfyUI и CUDA (если требуется).
    -   Копирование handler и скриптов.
    -   Реализация версии по `versions/<id>.json` на стадии запуска (build не зависит от lock).

-   `docker/handler/`
    -   `main.py` — CLI/серверная точка входа.
    -   `output.py` — код возврата результата (base64 / GCS upload).
    -   `resolver.py` — применение lock-файла (установка зависимостей, узлов, моделей).

### GCS интеграция

-   Поддерживаются переменные окружения для аутентификации и указания bucket.
-   При локальной отладке можно переключить вывод на base64/локальный файл.

### Тестирование (высокоуровнево)

-   Локальные проверки: init → `version.py create` → `version.py validate` → `version.py realize` → `version.py run-handler`.
-   Docker-проверка: build_docker → run handler → сравнение вывода с эталоном.
-   Репродукция: на основе одной спецификации собрать окружение дважды и сравнить SHA коммитов/хэши моделей.

### RunPod / Serverless (кратко)

-   Детальный гид: см. `docs/runpod.md`.
-   Дефолтные пути внутри образа: `COMFY_HOME=/workspace/ComfyUI`, `MODELS_DIR=/workspace/models` (переопределяйте переменными окружения при использовании volume).
-   Для Pods рекомендуется переопределять на volume: `/runpod-volume/builds/comfy-<id>`.
    -   Точка входа: `docker/entrypoint.sh` → `python -m rp_handler.main`.
    -   Параметры handler: `--version-id|--spec`, `--workflow`, `--output {base64|gcs}` (по умолчанию `gcs`), `--gcs-bucket`, `--gcs-prefix`, `--models-dir`, `--verbose`.
-   GCS переменные: `GCS_BUCKET`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`/`GCS_PROJECT`, `GCS_PREFIX`, `GCS_RETRIES`, `GCS_RETRY_BASE_SLEEP`, `GCS_PUBLIC`, `GCS_SIGNED_URL_TTL`, `GCS_VALIDATE`.
