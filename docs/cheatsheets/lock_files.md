# Работа с lock-файлами

## Просмотр содержимого lock-файла

```bash
cat lockfiles/comfy-my-version.lock.json | jq '.'
```

## Проверка версии ComfyUI в lock

```bash
cat lockfiles/comfy-my-version.lock.json | jq '.comfyui'
```

## Просмотр списка кастом нод

```bash
cat lockfiles/comfy-my-version.lock.json | jq '.custom_nodes[] | {name, commit}'
```

## Просмотр Python зависимостей

```bash
cat lockfiles/comfy-my-version.lock.json | jq '.python.packages[] | select(.name == "torch")'
```

## Просмотр списка моделей

```bash
cat lockfiles/comfy-my-version.lock.json | jq '.models[] | {name, source}'
```

## Сравнение двух lock-файлов

```bash
diff lockfiles/comfy-v1.lock.json lockfiles/comfy-v2.lock.json
```

## Или с jq для структурированного сравнения

```bash
jq -S '.comfyui.commit' lockfiles/comfy-v1.lock.json
jq -S '.comfyui.commit' lockfiles/comfy-v2.lock.json
```

## Создание lock-файла с нуля

```bash
python3 scripts/create_version.py --name "from-scratch" --pretty
```

## Обновление существующего lock-файла

```bash
python3 scripts/create_version.py --name "existing-version" --pretty  # перезапишет существующий
```

## Клонирование версии из lock-файла

```bash
./scripts/clone_version.sh --lock lockfiles/comfy-my-version.lock.json --target "$HOME/comfy-clone"
```

## Оффлайн клонирование с локальными wheels

```bash
./scripts/clone_version.sh \
  --lock lockfiles/comfy-my-version.lock.json \
  --target /runpod-volume/comfy \
  --offline --wheels-dir /wheels
```

## Параметры clone_version.sh

-   `--lock FILE` — путь к lock-файлу (обязательно)
-   `--target DIR` — целевая директория (обязательно)
-   `--python PYTHON` — базовый Python для утилит
-   `--skip-models` — пропустить скачивание моделей
-   `--offline` — установка без индексов (только локальные wheels)
-   `--wheels-dir DIR` — директория с wheel-артефактами
-   `--pip-extra-args "..."` — дополнительные аргументы для pip

## Удаление клонированной версии

```bash
./scripts/remove_version.sh --target "$HOME/comfy-clone"
```

## Удаление версии с моделями

```bash
./scripts/remove_version.sh --target "$HOME/comfy-clone" --remove-models --yes
```

## Параметры remove_version.sh

-   `--target DIR` — директория для удаления (обязательно)
-   `--yes` — без подтверждений
-   `--remove-models` — удалить каталог models
-   `--remove-root` — удалить корневую директорию
-   `--dry-run` — показать что будет удалено

## Верификация целостности lock-файла

```bash
python3 -c "import json; print('Valid JSON:', bool(json.load(open('lockfiles/comfy-my-version.lock.json'))))"
```

## Репродукция и сравнение версий

```bash
python3 scripts/repro_env_compare.py --lock lockfiles/comfy-my-version.lock.json --verbose
```

## Сравнение хэшей воркфлоу

```bash
# Записать эталон
python3 scripts/repro_workflow_hash.py \
  --lock lockfiles/comfy-my-version.lock.json \
  --workflow ./workflows/minimal.json \
  --baseline ./workflows/minimal.baseline.json \
  --mode record

# Сравнить с эталоном
python3 scripts/repro_workflow_hash.py \
  --lock lockfiles/comfy-my-version.lock.json \
  --workflow ./workflows/minimal.json \
  --baseline ./workflows/minimal.baseline.json \
  --mode compare
```

## Структура lock-файла

```json
{
    "version_name": "my-version",
    "schema_version": 1,
    "comfyui": {
        "repo": "https://github.com/comfyanonymous/ComfyUI",
        "commit": "abc123...",
        "path": null
    },
    "custom_nodes": [
        {
            "name": "gguf",
            "repo": "https://github.com/city96/ComfyUI-GGUF",
            "commit": "def456...",
            "path": "/path/to/custom_nodes/ComfyUI-GGUF"
        }
    ],
    "python": {
        "version": "3.11.0",
        "interpreter": "/usr/bin/python3",
        "packages": [
            {
                "name": "torch",
                "version": "2.3.0+cu124",
                "url": "https://download.pytorch.org/whl/cu124/torch-2.3.0%2Bcu124-cp311-cp311-linux_x86_64.whl"
            }
        ]
    },
    "models": [
        {
            "name": "flux-dev",
            "source": "hf://blackforestlabs/FLUX.1-dev/flux1-dev.safetensors",
            "target_path": "$MODELS_DIR/unet/flux1-dev.safetensors",
            "checksum": "sha256:..."
        }
    ]
}
```

## Резервное копирование lock-файлов

```bash
cp lockfiles/comfy-my-version.lock.json lockfiles/comfy-my-version.backup.json
```

## Поиск всех lock-файлов

```bash
ls -la lockfiles/comfy-*.lock.json
```

## Проверка размера lock-файла

```bash
ls -lh lockfiles/comfy-my-version.lock.json
wc -l lockfiles/comfy-my-version.lock.json
```
