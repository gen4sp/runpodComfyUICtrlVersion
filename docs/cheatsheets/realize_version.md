# Реализация версии из JSON (versions/\*.json)

## Назначение

Скрипт `scripts/realize_version.py` развертывает конкретную версию ComfyUI по декларативной JSON‑спецификации в `versions/<id>.json`:

-   создаёт изолированный `COMFY_HOME` с отдельным `.venv`
-   клонирует `ComfyUI` и кастом‑ноды по зафиксированным `commit SHA`
-   устанавливает pinned зависимости из lock‑файла
-   проверяет и докачивает модели по lock‑файлу

Подходит для локальной разработки, Pods на RunPod (volume) и CI.

## Формат JSON‑спеки

```json
{
    "version_id": "wan22-fast",
    "lock": "lockfiles/comfy-wan2.2.lock.json",
    "target": "/runpod-volume/comfy-wan22-fast",
    "options": {
        "offline": false,
        "skip_models": false,
        "wheels_dir": "/wheels",
        "pip_extra_args": "--no-cache-dir"
    }
}
```

-   `version_id`: идентификатор версии (имя для директории по умолчанию)
-   `lock`: путь к lock‑файлу с pinned зависимостями, узлами и моделями
-   `target`: куда развернуть окружение (иначе выбирается автоматически)
-   `options`: необязательные параметры клонирования/установки

## Команды

### Развёртка по id (ищет `versions/<id>.json`)

```bash
python3 scripts/realize_version.py --version-id wan22-fast
```

### Явный путь к спека‑файлу

```bash
python3 scripts/realize_version.py --spec versions/wan22-fast.json
```

### Переопределить lock и target

```bash
python3 scripts/realize_version.py \
  --spec versions/wan22-fast.json \
  --lock lockfiles/comfy-wan2.2.lock.json \
  --target /runpod-volume/comfy-wan22-fast
```

### Оффлайн режим (локальные wheels)

```bash
python3 scripts/realize_version.py --version-id wan22-fast --offline --wheels-dir /wheels
```

### Dry‑run (только показать действия)

```bash
python3 scripts/realize_version.py --version-id wan22-fast --dry-run
```

## Примечания

-   По умолчанию `target` выбирается так: `/runpod-volume/comfy-<id>` (если каталог существует) → `$HOME/comfy-<id>` → `./comfy-<id>`.
-   Каждый `target` содержит отдельный `.venv` (изоляция зависимостей по версии).
-   Модели проверяются/докачиваются в `$target/models` (можно монтировать volume на RunPod).
-   Скрипт вызывает `scripts/clone_version.sh`, который читает Python‑секции и модели из lock‑файла.
