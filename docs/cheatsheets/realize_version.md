# Реализация версии из JSON (versions/\*.json)

## Назначение

Скрипт `scripts/realize_version.py` развертывает конкретную версию ComfyUI по декларативной JSON‑спецификации в `versions/<id>.json`:

-   создаёт изолированный `COMFY_HOME` с отдельным `.venv`
-   клонирует `ComfyUI` и кастом‑ноды по зафиксированным `commit SHA`
-   устанавливает зависимости и кастом‑ноды по `resolved-lock`
-   проверяет и докачивает модели в единый `MODELS_DIR`

Подходит для локальной разработки, Pods на RunPod (volume) и CI.

## Формат JSON‑спеки

```json
{
    "schema_version": 2,
    "version_id": "wan22-fast",
    "comfy": {
        "repo": "https://github.com/comfyanonymous/ComfyUI",
        "ref": "master"
    },
    "custom_nodes": [
        { "repo": "https://github.com/city96/ComfyUI-GGUF", "name": "gguf" }
    ],
    "models": [{ "source": "hf://...", "target_subdir": "unet" }],
    "env": {},
    "options": { "offline": false, "skip_models": false }
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

### Дополнительные опции

```bash
python3 scripts/realize_version.py \
  --spec versions/wan22-fast.json \
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
