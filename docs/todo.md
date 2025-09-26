## План переделки под единую спецификацию версий (versions/\*.json)

Цель: описывать версии только в `versions/*.json` и запускать по `--version-id`, без `lockfiles/*`. Компоненты не дублируются: модели всегда из одного места (`MODELS_DIR`/extra_model_paths), кастом‑ноды линкуются из кеша `<repo>@<commit>`. Handler сам резолвит и разворачивает окружение максимально быстро.

### 0. База и договорённости (согласно `docs/qa.md`) — выполнено

-   schema_version в `versions/*.json` — введён (`schema_version: 2`), пример обновлён (`versions/test-ver.json`)
-   Пиннинг: `repo` + опциональный `ref`; `commit` резолвится при первом запуске (`rp_handler.resolver.resolve_version_spec`)
-   Resolved‑lock сохраняем в `~/.cache/runpod-comfy/resolved/<version_id>.lock.json` (`save_resolved_lock`)
-   Модели: checksum не обязателен; ключ — URL; «одно место» через единый кеш (`COMFY_CACHE_ROOT/models`, дефолт `~/.cache/runpod-comfy/models`), в версии — только symlink
-   Кастом‑ноды: «чистые» коммиты; кеш `<repo>@<commit>` хранится под `COMFY_CACHE_ROOT/custom_nodes`; в версию — symlink
-   Offline: допускаем частичные загрузки; symlink разрешены (при offline отсутствующие модели — warn)
-   Обратную совместимость с `--lock` — убрана из handler/скриптов; интерфейс теперь `--version-id/--spec`

### 1. Схема и валидация спецификации версий — выполнено

1.1 Ввести схему (schema_version=2):

-   `version_id`, `comfy: {repo, ref?, commit?}`
-   `custom_nodes: [{repo, ref?, commit?, name?}]`
-   `models: [{source, name?, target_subdir?}]`
-   `env?`, `options?: {offline?, skip_models?}`
    1.2 Реализовать валидацию схемы и понятные ошибки
    1.3 Обновить документацию и примеры

### 2. Резолвер refs→commits и resolved‑lock — выполнено

2.1 Реализовать резолвинг `comfy` и `custom_nodes`
2.2 Сохранять результат в `~/.comfy-cache/resolved/<version_id>.lock.json`
2.3 Идемпотентность при повторном запуске
2.4 Поддержать `--dry-run` (печать плана)

### 3. Развёртывание версии (realize) — выполнено

-   `realize_version.py` принимает новую спецификацию (`--version-id/--spec`), делает резолв + realize без `lock`
-   `COMFY_HOME=/runpod-volume/comfy-<version_id>` по умолчанию, создаёт отдельный `.venv`
-   Автосбор зависимостей ядра и кастом-нода (requirements/pyproject) с поддержкой wheels через `--wheels-dir`
-   Кастом‑ноды клонируются в кеш `<repo>@<commit>` под `COMFY_CACHE_ROOT/custom_nodes`, в `COMFY_HOME/custom_nodes/<name>` создаются symlink'и
-   Модели загружаются в общий `MODELS_DIR` и линкуются из кеша (`COMFY_CACHE_ROOT/models`)
-   Генерируется и подключается `extra_model_paths.yaml`
-   Офлайн-режим использует локальные данные, отсутствующее помечается предупреждениями

### 4. Handler — выполнено

-   Интерфейс принимает только `--version-id` и `--workflow`, без `--lock`
-   Внутри: резолв → реалайз → запуск воркфлоу; быстрый повторный старт сохранён
-   Параметры вывода (GCS и т.п.) без изменений

### 5. CLI верхнего уровня — выполнено

-   Добавлен `scripts/version.py` с командами `resolve`, `realize`, `test`
-   `scripts/run_handler_local.sh` обновлён на `--version-id`

### 6. Документация

6.1 Обновить cheatsheets (`README.md`, `create_version.md`, `realize_version.md`, `runpod_local.md`) под новую схему
6.2 Удалить/архивировать разделы про `lockfiles`; убрать упоминания `--lock`
6.3 Добавить раздел про `MODELS_DIR` и `extra_model_paths.yaml`

### 7. Миграция и чистка

7.1 Привести существующие `versions/*.json` к новой схеме
7.2 Удалить легаси‑флаги/код (`--lock` и связанные пути)

### 8. Критерии приёмки

-   `handler run --version-id <id> --workflow <wf>` перезапускается без повторной скачки/клонирования
-   Модели используются из одного места (`MODELS_DIR`), без дублирования
-   Кастом‑ноды из кеша `<repo>@<commit>` линкуются в версию
-   `--dry-run` печатает полный план действий
-   Offline допускает частичный запуск

### 9. Риски и решения

-   Неодинаковые пути моделей — стандартизовать через `MODELS_DIR` и/или `extra_model_paths.yaml`
-   Конфликты нод — изоляция по `<repo>@<commit>`
-   Долгий первый резолв — кешировать результат и wheels

### 10. Этапность

-   Этап 1: схема + резолвер + realize (локально)
-   Этап 2: handler и `run_handler_local.sh`
-   Этап 3: документация и чистка легаси
-   Этап 4: UX‑CLI `scripts/version.py` и smoke‑test
