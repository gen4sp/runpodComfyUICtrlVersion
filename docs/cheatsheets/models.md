# Установка моделей

## Валидация и скачивание моделей из YAML

```bash
export COMFY_HOME="$HOME/comfy"
python3 scripts/validate_yaml_models.py --models-dir "$COMFY_HOME/models"
```

## Скачивание конкретного YAML файла

```bash
python3 scripts/validate_yaml_models.py --yaml models/flux-models.yml --models-dir "$COMFY_HOME/models"
```

## Валидация моделей без скачивания

```bash
python3 scripts/validate_yaml_models.py --yaml models/wan22-fast-models.yml --models-dir "$COMFY_HOME/models" --validate-only
```

## Верификация моделей из lock-файла

```bash
python3 scripts/verify_models.py --lock lockfiles/comfy-my-version.lock.json --models-dir "$COMFY_HOME/models"
```

## Восстановление отсутствующих моделей

```bash
python3 scripts/verify_models.py --lock lockfiles/comfy-my-version.lock.json --models-dir "$COMFY_HOME/models" --overwrite --verbose
```

## Параметры validate_yaml_models.py

-   `--yaml FILE` — конкретный YAML файл (по умолчанию: все в models/)
-   `--models-dir DIR` — директория моделей (обязательно)
-   `--validate-only` — только проверка без скачивания
-   `--overwrite` — перезаписывать существующие файлы
-   `--workers N` — количество параллельных потоков (по умолчанию: 4)
-   `--timeout SEC` — таймаут загрузки (по умолчанию: 120)

> **Предупреждение**: Кеш не используется и не рекомендуется. Все модели скачиваются напрямую в директорию назначения.

## Параметры verify_models.py

-   `--lock FILE` — путь к lock-файлу (обязательно)
-   `--models-dir DIR` — базовая директория моделей
-   `--overwrite` — перезаписывать при несоответствии checksum
-   `--timeout SEC` — таймаут сетевых загрузок
-   `--verbose` — подробный вывод

## Поддерживаемые источники моделей

### Hugging Face

```yaml
models:
    - name: "flux-dev"
      source: "hf://blackforestlabs/FLUX.1-dev/flux1-dev.safetensors"
      target_path: "$MODELS_DIR/unet/flux1-dev.safetensors"
```

```bash
export HF_TOKEN="hf_xxxxxxxxxxxxxxxxxxxxxxxxx"  # для приватных репозиториев
```

### Civitai

```yaml
models:
    - name: "my-lora"
      source: "civitai://models/12345"
      target_path: "$MODELS_DIR/loras/my-lora.safetensors"
```

```bash
export CIVITAI_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxx"
```

### HTTP/HTTPS

```yaml
models:
    - name: "model"
      source: "https://example.com/model.safetensors"
      target_path: "$MODELS_DIR/checkpoints/model.safetensors"
```

### Локальные файлы

```yaml
models:
    - name: "local-model"
      source: "file:///path/to/local/model.safetensors"
      target_path: "$MODELS_DIR/checkpoints/model.safetensors"
```

### Google Cloud Storage

```yaml
models:
    - name: "gcs-model"
      source: "gs://my-bucket/models/model.safetensors"
      target_path: "$MODELS_DIR/checkpoints/model.safetensors"
```

## Переменные в target_path

-   `$COMFY_HOME` — директория установки ComfyUI
-   `$MODELS_DIR` — базовая директория моделей (обычно $COMFY_HOME/models)

## Примеры YAML файлов

### Простой пример (models/ctest.yml)

```yaml
models:
    - name: "wan-lora-model-1996092"
      source: "civitai://api/download/models/1996092?type=Model&format=SafeTensor"
      target_path: "$MODELS_DIR/loras/wan_lora_model_1996092.safetensors"
```

### Сложный пример (models/wan22-fast-models.yml)

```yaml
models:
    - name: "wan2.2-t2v-high-noise-14b-fp8-scaled"
      source: "hf://Comfy-Org/Wan_2.2_ComfyUI_Repackaged/split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"
      target_path: "$MODELS_DIR/unet/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"
    - name: "umt5-xxl-fp8-e4m3fn-scaled"
      source: "hf://ratoenien/umt5_xxl_fp8_e4m3fn_scaled/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
      target_path: "$MODELS_DIR/clip/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
```
