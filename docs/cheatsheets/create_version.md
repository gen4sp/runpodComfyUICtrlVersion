# Создание новой версии ComfyUI

## Создание базовой версии с фиксацией зависимостей

```bash
python3 scripts/create_version.py --name "my-version" --comfy-repo https://github.com/comfyanonymous/ComfyUI --requirements ./requirements.txt --pretty
```

## Создание версии с кастом нодами

```bash
python3 scripts/create_version.py \
  --name "flux-version" \
  --comfy-repo https://github.com/comfyanonymous/ComfyUI \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf \
  --requirements ./requirements.txt \
  --models-spec ./models/flux-models.yml \
  --pretty
```

## Создание версии с несколькими кастом нодами

```bash
python3 scripts/create_version.py \
  --name "wan-version" \
  --comfy-repo https://github.com/comfyanonymous/ComfyUI \
  --custom-node repo=https://github.com/kijai/ComfyUI-WanVideoWrapper,name=wan-wrapper \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf \
  --requirements ./requirements.txt \
  --models-spec ./models/wan22-fast-models.yml \
  --pretty
```

## Создание версии с явными путями

```bash
export COMFY_HOME="$HOME/comfy"
python3 scripts/create_version.py \
  --name "local-version" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  --models-spec ./models/ctest.yml \
  --pretty
```

## Параметры скрипта create_version.py

-   `--name` — имя версии (обязательно, попадет в lockfiles/comfy-<name>.lock.json)
-   `--comfy-path` — путь к локальному репозиторию ComfyUI
-   `--comfy-repo` — URL репозитория для метаданных
-   `--custom-node` — кастом ноды (можно повторять):
    -   `repo=URL` — URL репозитория
    -   `name=NAME` — имя ноды
    -   `path=PATH` — локальный путь
    -   `commit=SHA` — конкретный коммит
-   `--venv` — путь к виртуальному окружению
-   `--requirements` — файл с pinned зависимостями
-   `--models-spec` — YAML/JSON со списком моделей
-   `--models-dir` — базовая директория для моделей (по умолчанию `$COMFY_HOME/models`)
-   `--output` — путь для сохранения lock-файла (по умолчанию `lockfiles/comfy-<name>.lock.json`)
-   `--pretty` — человекочитаемый JSON
-   `--wheel-url name=url` — подмена URL для пакета

## Примеры моделей в YAML

```yaml
models:
    - name: "flux-dev"
      source: "hf://blackforestlabs/FLUX.1-dev/flux1-dev.safetensors"
      target_path: "$MODELS_DIR/unet/flux1-dev.safetensors"
    - name: "clip-l"
      source: "hf://comfyanonymous/flux_text_encoders/t5xxl_fp8_e4m3fn.safetensors"
      target_path: "$MODELS_DIR/clip/t5xxl_fp8_e4m3fn.safetensors"
```

## Проверка созданного lock-файла

## Быстрое применение версии из JSON

После создания lock‑файла можно оформить спека‑версию и развернуть её:

```bash
# versions/my-version.json
cat > versions/my-version.json << 'JSON'
{
  "version_id": "my-version",
  "lock": "lockfiles/comfy-my-version.lock.json"
}
JSON

# Развернуть окружение (создаст отдельный .venv и докачает модели)
python3 scripts/realize_version.py --version-id "my-version"
```

```bash
cat lockfiles/comfy-my-version.lock.json | jq '.version_name'
```
