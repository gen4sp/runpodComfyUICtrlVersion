# Создание минимальной базовой версии

## Создание чистой базовой версии без зависимостей

```bash
export COMFY_HOME="$HOME/comfy-base"
./scripts/init_comfyui.sh --path "$COMFY_HOME" --install-torch skip

cd "$COMFY_HOME"
source .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

python3 ~/runpodComfyuiVersionControl/scripts/create_version.py \
  --name "base-cpu" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  --pretty
```

## Создание базовой версии с основными нодами

```bash
export COMFY_HOME="$HOME/comfy-core"
./scripts/init_comfyui.sh --path "$COMFY_HOME" --install-torch auto

cd "$COMFY_HOME"
source .venv/bin/activate

# Установка основных кастом нод
git clone https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
cd custom_nodes/ComfyUI-GGUF && pip install -r requirements.txt && cd ../..

git clone https://github.com/kijai/ComfyUI-VideoHelperSuite custom_nodes/ComfyUI-VideoHelperSuite
cd custom_nodes/ComfyUI-VideoHelperSuite && pip install -r requirements.txt && cd ../..

git clone https://github.com/Fannovel16/comfyui_controlnet_aux custom_nodes/comfyui_controlnet_aux
cd custom_nodes/comfyui_controlnet_aux && pip install -r requirements.txt && cd ../..

# Создание версии
python3 ~/runpodComfyuiVersionControl/scripts/create_version.py \
  --name "base-with-core-nodes" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf \
  --custom-node repo=https://github.com/kijai/ComfyUI-VideoHelperSuite,name=video-helper \
  --custom-node repo=https://github.com/Fannovel16/comfyui_controlnet_aux,name=controlnet-aux \
  --pretty
```

## Создание базовой версии для FLUX

```bash
export COMFY_HOME="$HOME/comfy-flux-base"
./scripts/init_comfyui.sh --path "$COMFY_HOME" --install-torch auto

cd "$COMFY_HOME"
source .venv/bin/activate

# Установка FLUX-специфичных нод
git clone https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
cd custom_nodes/ComfyUI-GGUF && pip install -r requirements.txt && cd ../..

git clone https://github.com/XLabs-AI/x-flux-comfyui custom_nodes/x-flux-comfyui
cd custom_nodes/x-flux-comfyui && pip install -r requirements.txt && cd ../..

# Создание версии
python3 ~/runpodComfyuiVersionControl/scripts/create_version.py \
  --name "flux-base" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf \
  --custom-node repo=https://github.com/XLabs-AI/x-flux-comfyui,name=x-flux \
  --models-spec ~/runpodComfyuiVersionControl/models/flux-models.yml \
  --pretty
```

## Создание базовой версии для Wan

```bash
export COMFY_HOME="$HOME/comfy-wan-base"
./scripts/init_comfyui.sh --path "$COMFY_HOME" --install-torch auto

cd "$COMFY_HOME"
source .venv/bin/activate

# Установка Wan-специфичных нод
git clone https://github.com/kijai/ComfyUI-WanVideoWrapper custom_nodes/ComfyUI-WanVideoWrapper
cd custom_nodes/ComfyUI-WanVideoWrapper && pip install -r requirements.txt && cd ../..

git clone https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
cd custom_nodes/ComfyUI-GGUF && pip install -r requirements.txt && cd ../..

# Создание версии
python3 ~/runpodComfyuiVersionControl/scripts/create_version.py \
  --name "wan-base" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  --custom-node repo=https://github.com/kijai/ComfyUI-WanVideoWrapper,name=wan-wrapper \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf \
  --models-spec ~/runpodComfyuiVersionControl/models/wan22-fast-models.yml \
  --pretty
```

## Создание минимальной версии для тестирования

```bash
export COMFY_HOME="$HOME/comfy-minimal"
./scripts/init_comfyui.sh --path "$COMFY_HOME" --install-torch skip

cd "$COMFY_HOME"
source .venv/bin/activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Создание версии без моделей
python3 ~/runpodComfyuiVersionControl/scripts/create_version.py \
  --name "minimal-cpu" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  --pretty
```

## Тестирование базовой версии

```bash
# Клонирование для тестирования
./scripts/clone_version.sh --lock lockfiles/comfy-base-cpu.lock.json --target "$HOME/test-base"

# Запуск
cd "$HOME/test-base"
source .venv/bin/activate
python ComfyUI/main.py --listen 0.0.0.0 --port 8188
```

## Добавление моделей к базовой версии

```bash
# Скачивание базовых моделей
python3 scripts/validate_yaml_models.py \
  --yaml models/ctest.yml \
  --models-dir "$COMFY_HOME/models"

# Обновление lock-файла
python3 scripts/create_version.py \
  --name "base-with-models" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  --models-spec models/ctest.yml \
  --pretty
```

## Создание версии для конкретного use case

```bash
# Для текст-в-видео с Wan
export COMFY_HOME="$HOME/comfy-t2v"
./scripts/clone_version.sh --lock lockfiles/comfy-wan-base.lock.json --target "$COMFY_HOME"

cd "$COMFY_HOME"
source .venv/bin/activate

# Добавление специфичных моделей
python3 ~/runpodComfyuiVersionControl/scripts/validate_yaml_models.py \
  --yaml ~/runpodComfyuiVersionControl/models/wan22-fast-models.yml \
  --models-dir "$COMFY_HOME/models"

# Финальная версия для T2V
python3 ~/runpodComfyuiVersionControl/scripts/create_version.py \
  --name "wan-t2v-ready" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  --custom-node repo=https://github.com/kijai/ComfyUI-WanVideoWrapper,name=wan-wrapper \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf \
  --models-spec ~/runpodComfyuiVersionControl/models/wan22-fast-models.yml \
  --pretty
```

## Стратегия создания базовых версий

1. **Базовая версия**: минимальный ComfyUI + базовые зависимости
2. **Core версия**: базовая + основные кастом ноды (GGUF, VideoHelperSuite, ControlNet)
3. **Domain версия**: core + специфичные для домена ноды (FLUX, Wan, SD)
4. **Use-case версия**: domain + модели + оптимизации для конкретной задачи

## Примеры базовых версий

### base-cpu (минимальная)

-   ComfyUI core
-   PyTorch CPU
-   Без кастом нод
-   Без моделей

### base-gpu (расширенная)

-   ComfyUI core
-   PyTorch CUDA
-   Основные кастом ноды
-   Базовые модели

### flux-base (для FLUX)

-   base-gpu
-   FLUX-specific ноды
-   FLUX модели

### wan-base (для Wan)

-   base-gpu
-   Wan-specific ноды
-   Wan модели

### audio-base (для MMAudio)

-   base-gpu
-   Audio-specific ноды
-   Audio модели

## Автоматизация создания базовых версий

```bash
#!/bin/bash
# create_base_version.sh

VERSION_TYPE=$1
COMFY_HOME="$HOME/comfy-${VERSION_TYPE}"

case $VERSION_TYPE in
    "minimal")
        TORCH_MODE="skip"
        CUSTOM_NODES=""
        MODELS_SPEC=""
        ;;
    "core")
        TORCH_MODE="auto"
        CUSTOM_NODES="--custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf"
        MODELS_SPEC=""
        ;;
    "flux")
        TORCH_MODE="auto"
        CUSTOM_NODES="--custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf --custom-node repo=https://github.com/XLabs-AI/x-flux-comfyui,name=x-flux"
        MODELS_SPEC="--models-spec models/flux-models.yml"
        ;;
    "wan")
        TORCH_MODE="auto"
        CUSTOM_NODES="--custom-node repo=https://github.com/kijai/ComfyUI-WanVideoWrapper,name=wan-wrapper --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf"
        MODELS_SPEC="--models-spec models/wan22-fast-models.yml"
        ;;
esac

./scripts/init_comfyui.sh --path "$COMFY_HOME" --install-torch $TORCH_MODE

# Здесь должна быть логика установки кастом нод...

python3 scripts/create_version.py \
  --name "${VERSION_TYPE}-base" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  $CUSTOM_NODES \
  $MODELS_SPEC \
  --pretty
```
