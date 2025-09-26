# Создание новой версии ComfyUI (schema v2)

## Быстрый старт

```bash
python3 scripts/version.py create "my-version" \
  --repo https://github.com/comfyanonymous/ComfyUI@main \
  --nodes https://github.com/comfyanonymous/ComfyUI-Custom-Scripts@main \
  --models '{"source": "https://example.com/model.safetensors", "target_subdir": "checkpoints"}'
```

## Несколько кастом нод

```bash
python3 scripts/version.py create "wan-version" \
  --repo https://github.com/comfyanonymous/ComfyUI@main \
  --nodes https://github.com/kijai/ComfyUI-WanVideoWrapper@main \
  --nodes https://github.com/city96/ComfyUI-GGUF@main \
  --models '{"source": "https://huggingface.co/.../model.safetensors", "target_subdir": "unet"}'
```

## Модели через файл JSON/YAML

```bash
python3 scripts/version.py create "flux" \
  --repo https://github.com/comfyanonymous/ComfyUI@main \
  --models models/flux-models.json
```

## Автоматическое вычисление checksum

```bash
python3 scripts/version.py create "local" \
  --repo https://github.com/comfyanonymous/ComfyUI@main \
  --models-root "$MODELS_DIR" \
  --auto-checksum \
  --models '{"source": "file:///workspace/models/my.safetensors", "target_subdir": "checkpoints"}'
```

## Параметры `scripts/version.py create`

-   `version_id` — имя версии (используется как `versions/<id>.json`).
-   `--repo URL[@ref]` — репозиторий ComfyUI, ref опционален; commit резолвится автоматически.
-   `--nodes VALUE` — можно повторять. VALUE: JSON-объект, файл или строка `<repo>@<ref>`.
-   `--models VALUE` — можно повторять. VALUE: JSON-объект или файл со списком объектов.
-   `--models-root PATH` — база локальных моделей для авто-checksum.
-   `--auto-checksum` — вычислить `sha256` для найденных локальных моделей.
-   `--output PATH` — путь для сохранения спеки (по умолчанию `versions/<id>.json`).

## Структура модели

```json
{
    "source": "https://example.com/model.safetensors",
    "target_subdir": "checkpoints",
    "target_path": "checkpoints/model.safetensors",
    "name": "model.safetensors",
    "checksum": "sha256:..."
}
```

## После создания

```bash
# Проверить, что спецификация резолвится
python3 scripts/version.py resolve my-version

# Развернуть
python3 scripts/version.py realize my-version
```
