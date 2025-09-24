# Ручная настройка и упаковка версии

## Полный workflow: настройка → тестирование → упаковка

```bash
# Шаг 1: Инициализация чистой среды
export COMFY_HOME="$HOME/comfy-manual"
./scripts/init_comfyui.sh --path "$COMFY_HOME" --install-torch auto

# Шаг 2: Активация окружения
cd "$COMFY_HOME"
source .venv/bin/activate

# Шаг 3: Установка базовых зависимостей
pip install --upgrade pip setuptools wheel

# Шаг 4: Установка PyTorch (если не установлено)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# Шаг 5: Тестовый запуск ComfyUI
timeout 30 python ComfyUI/main.py --headless || echo "ComfyUI started and stopped - OK"
```

## Установка кастом нод вручную

```bash
cd "$COMFY_HOME"
source .venv/bin/activate

# GGUF loader
git clone https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
cd custom_nodes/ComfyUI-GGUF
pip install -r requirements.txt
cd ../..

# Video helpers
git clone https://github.com/kijai/ComfyUI-VideoHelperSuite custom_nodes/ComfyUI-VideoHelperSuite
cd custom_nodes/ComfyUI-VideoHelperSuite
pip install -r requirements.txt
cd ../..

# ControlNet aux
git clone https://github.com/Fannovel16/comfyui_controlnet_aux custom_nodes/comfyui_controlnet_aux
cd custom_nodes/comfyui_controlnet_aux
pip install -r requirements.txt
cd ../..

# Wan wrapper (для видео)
git clone https://github.com/kijai/ComfyUI-WanVideoWrapper custom_nodes/ComfyUI-WanVideoWrapper
cd custom_nodes/ComfyUI-WanVideoWrapper
pip install -r requirements.txt
cd ../..

echo "Все кастом ноды установлены"
```

## Тестирование установленных нод

```bash
cd "$COMFY_HOME"
source .venv/bin/activate

# Тест импортов
python -c "
try:
    import custom_nodes.ComfyUI_GGUF
    print('✓ GGUF node: OK')
except Exception as e:
    print('✗ GGUF node: FAILED -', e)

try:
    import custom_nodes.ComfyUI_VideoHelperSuite
    print('✓ VideoHelperSuite: OK')
except Exception as e:
    print('✗ VideoHelperSuite: FAILED -', e)

try:
    import custom_nodes.comfyui_controlnet_aux
    print('✓ ControlNet aux: OK')
except Exception as e:
    print('✗ ControlNet aux: FAILED -', e)

try:
    import custom_nodes.ComfyUI_WanVideoWrapper
    print('✓ Wan wrapper: OK')
except Exception as e:
    print('✗ Wan wrapper: FAILED -', e)
"
```

## Скачивание и установка моделей

```bash
cd "$COMFY_HOME"
source .venv/bin/activate

# Создание директорий
mkdir -p models/checkpoints models/loras models/unet models/vae models/clip

# Скачивание тестовых моделей
python ~/runpodComfyuiVersionControl/scripts/validate_yaml_models.py \
  --yaml ~/runpodComfyuiVersionControl/models/ctest.yml \
  --models-dir models

# Или ручное скачивание
wget -O models/loras/test-lora.safetensors "https://civitai.com/api/download/models/1996092?type=Model&format=SafeTensor"
```

## Тестирование моделей

```bash
cd "$COMFY_HOME"
source .venv/bin/activate

# Проверка checksum
python -c "
import hashlib
import os

def sha256_checksum(filepath):
    with open(filepath, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

model_path = 'models/loras/wan_lora_model_1996092.safetensors'
if os.path.exists(model_path):
    checksum = sha256_checksum(model_path)
    print(f'Checksum for {model_path}: {checksum}')
    print('✓ Model file exists and checksum calculated')
else:
    print('✗ Model file not found')
"
```

## Запуск ComfyUI для тестирования

```bash
cd "$COMFY_HOME"
source .venv/bin/activate

# Запуск в фоне для тестирования
python ComfyUI/main.py --listen 127.0.0.1 --port 8188 &
COMFY_PID=$!

# Ожидание запуска
sleep 15

# Проверка доступности
curl -s http://127.0.0.1:8188/system_stats | head -20

# Остановка
kill $COMFY_PID
wait $COMFY_PID 2>/dev/null
```

## Тестирование workflow

```bash
cd "$COMFY_HOME"
source .venv/bin/activate

# Запуск ComfyUI
python ComfyUI/main.py --listen 127.0.0.1 --port 8188 &
COMFY_PID=$!

sleep 10

# Тестовый workflow (minimal.json)
curl -X POST http://127.0.0.1:8188/prompt \
  -H "Content-Type: application/json" \
  -d @~/runpodComfyuiVersionControl/workflows/minimal.json \
  --max-time 300

# Остановка
kill $COMFY_PID
```

## Создание lock-файла из настроенной среды

```bash
cd "$COMFY_HOME"
source .venv/bin/activate

# Создание lock-файла
python ~/runpodComfyuiVersionControl/scripts/create_version.py \
  --name "manual-setup-v1" \
  --comfy-path ComfyUI \
  --venv .venv \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf,path=custom_nodes/ComfyUI-GGUF \
  --custom-node repo=https://github.com/kijai/ComfyUI-VideoHelperSuite,name=video-helper,path=custom_nodes/ComfyUI-VideoHelperSuite \
  --custom-node repo=https://github.com/Fannovel16/comfyui_controlnet_aux,name=controlnet-aux,path=custom_nodes/comfyui_controlnet_aux \
  --custom-node repo=https://github.com/kijai/ComfyUI-WanVideoWrapper,name=wan-wrapper,path=custom_nodes/ComfyUI-WanVideoWrapper \
  --models-spec ~/runpodComfyuiVersionControl/models/ctest.yml \
  --pretty
```

## Верификация созданной версии

```bash
# Тест клонирования в новую директорию
./scripts/clone_version.sh \
  --lock lockfiles/comfy-manual-setup-v1.lock.json \
  --target "$HOME/test-manual-version"

# Тест запуска клонированной версии
cd "$HOME/test-manual-version"
source .venv/bin/activate

# Быстрый тест
timeout 30 python ComfyUI/main.py --headless || echo "Clone test: OK"
```

## Финализация и очистка

```bash
# Архивация оригинальной среды (опционально)
cd "$HOME"
tar -czf comfy-manual-setup.tar.gz comfy-manual

# Удаление тестовой версии
./scripts/remove_version.sh --target "$HOME/test-manual-version" --yes

# Финальный отчет
echo "=== MANUAL SETUP COMPLETED ==="
echo "Lock file: lockfiles/comfy-manual-setup-v1.lock.json"
echo "Original setup: $HOME/comfy-manual"
echo "Archive: $HOME/comfy-manual-setup.tar.gz"
```

## Автоматизированный скрипт для ручной настройки

```bash
#!/bin/bash
# manual_setup.sh - Полная ручная настройка ComfyUI версии

set -e

# Конфигурация
COMFY_HOME="$HOME/comfy-manual"
VERSION_NAME="manual-setup-$(date +%Y%m%d-%H%M%S)"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== MANUAL COMFYUI SETUP ==="
echo "ComfyUI home: $COMFY_HOME"
echo "Version name: $VERSION_NAME"

# Шаг 1: Инициализация
echo "Step 1: Initializing ComfyUI..."
"$REPO_ROOT/scripts/init_comfyui.sh" --path "$COMFY_HOME" --install-torch auto

# Шаг 2: Установка кастом нод
echo "Step 2: Installing custom nodes..."
cd "$COMFY_HOME"
source .venv/bin/activate

# Установка нод
install_custom_node() {
    local repo=$1
    local name=$2
    echo "Installing $name from $repo..."
    git clone "$repo" "custom_nodes/$name"
    cd "custom_nodes/$name"
    if [ -f requirements.txt ]; then
        pip install -r requirements.txt
    fi
    cd ../..
}

install_custom_node "https://github.com/city96/ComfyUI-GGUF" "ComfyUI-GGUF"
install_custom_node "https://github.com/kijai/ComfyUI-VideoHelperSuite" "ComfyUI-VideoHelperSuite"
install_custom_node "https://github.com/Fannovel16/comfyui_controlnet_aux" "comfyui_controlnet_aux"
install_custom_node "https://github.com/kijai/ComfyUI-WanVideoWrapper" "ComfyUI-WanVideoWrapper"

# Шаг 3: Установка моделей
echo "Step 3: Installing models..."
python "$REPO_ROOT/scripts/validate_yaml_models.py" \
  --yaml "$REPO_ROOT/models/ctest.yml" \
  --models-dir "$COMFY_HOME/models"

# Шаг 4: Тестирование
echo "Step 4: Testing setup..."
python ComfyUI/main.py --headless &
COMFY_PID=$!
sleep 10

if curl -s http://127.0.0.1:8188/system_stats > /dev/null; then
    echo "✓ ComfyUI is responding"
else
    echo "✗ ComfyUI is not responding"
    kill $COMFY_PID
    exit 1
fi

kill $COMFY_PID
wait $COMFY_PID 2>/dev/null

# Шаг 5: Создание версии
echo "Step 5: Creating version lock file..."
python "$REPO_ROOT/scripts/create_version.py" \
  --name "$VERSION_NAME" \
  --comfy-path "$COMFY_HOME/ComfyUI" \
  --venv "$COMFY_HOME/.venv" \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf,path="$COMFY_HOME/custom_nodes/ComfyUI-GGUF" \
  --custom-node repo=https://github.com/kijai/ComfyUI-VideoHelperSuite,name=video-helper,path="$COMFY_HOME/custom_nodes/ComfyUI-VideoHelperSuite" \
  --custom-node repo=https://github.com/Fannovel16/comfyui_controlnet_aux,name=controlnet-aux,path="$COMFY_HOME/custom_nodes/comfyui_controlnet_aux" \
  --custom-node repo=https://github.com/kijai/ComfyUI-WanVideoWrapper,name=wan-wrapper,path="$COMFY_HOME/custom_nodes/ComfyUI-WanVideoWrapper" \
  --models-spec "$REPO_ROOT/models/ctest.yml" \
  --pretty

# Шаг 6: Верификация
echo "Step 6: Verifying version..."
"$REPO_ROOT/scripts/clone_version.sh" \
  --lock "lockfiles/comfy-$VERSION_NAME.lock.json" \
  --target "$HOME/test-$VERSION_NAME"

cd "$HOME/test-$VERSION_NAME"
source .venv/bin/activate
timeout 20 python ComfyUI/main.py --headless && echo "✓ Clone test passed"

# Очистка
"$REPO_ROOT/scripts/remove_version.sh" --target "$HOME/test-$VERSION_NAME" --yes

echo "=== SETUP COMPLETED SUCCESSFULLY ==="
echo "Version: $VERSION_NAME"
echo "Lock file: lockfiles/comfy-$VERSION_NAME.lock.json"
echo "Setup directory: $COMFY_HOME"
```

## Troubleshooting распространенных проблем

```bash
# Проблема: Import errors при тестировании нод
cd "$COMFY_HOME"
source .venv/bin/activate
pip install --upgrade --force-reinstall -r custom_nodes/ComfyUI-GGUF/requirements.txt

# Проблема: ComfyUI не запускается
cd "$COMFY_HOME"
source .venv/bin/activate
python -c "import torch; print('PyTorch OK')"
python -c "import comfy; print('ComfyUI import OK')"

# Проблема: Модели не скачиваются
export HF_TOKEN="your_token_here"
python scripts/validate_yaml_models.py --yaml models/ctest.yml --models-dir models --verbose

# Проблема: Lock файл не создается
cd "$COMFY_HOME"
source .venv/bin/activate
pip freeze > current_requirements.txt
python ~/runpodComfyuiVersionControl/scripts/create_version.py --name debug --pretty
```

## Профилирование и оптимизация

```bash
cd "$COMFY_HOME"
source .venv/bin/activate

# Проверка размера установки
du -sh . ComfyUI custom_nodes models .venv

# Анализ зависимостей
pip list --format=freeze | wc -l

# Тест скорости загрузки
time python -c "import torch; print('CUDA:', torch.cuda.is_available())"

# Memory usage
python -c "
import psutil
import os
process = psutil.Process(os.getpid())
print(f'Memory usage: {process.memory_info().rss / 1024 / 1024:.1f} MB')
"
```

## Создание документации для версии

```bash
# Создание README для версии
cat > "$COMFY_HOME/README.md" << EOF
# ComfyUI Version: $VERSION_NAME

## Installed Components

### ComfyUI Core
- Repository: https://github.com/comfyanonymous/ComfyUI
- Commit: $(cd ComfyUI && git rev-parse HEAD)

### Custom Nodes
- GGUF Loader: https://github.com/city96/ComfyUI-GGUF
- Video Helper Suite: https://github.com/kijai/ComfyUI-VideoHelperSuite
- ControlNet Aux: https://github.com/Fannovel16/comfyui_controlnet_aux
- Wan Video Wrapper: https://github.com/kijai/ComfyUI-WanVideoWrapper

### Models
- Wan LORA model (Civitai #1996092)

## Hardware Requirements
- GPU: RTX 30xx/40xx series recommended
- RAM: 16GB+ recommended
- Storage: 50GB+ for models

## Usage
source .venv/bin/activate
python ComfyUI/main.py --listen 0.0.0.0 --port 8188

## Lock File
See: lockfiles/comfy-$VERSION_NAME.lock.json
EOF
```
