# Запуск версии вне докера на RunPod

## Запуск handler локально для тестирования

```bash
./scripts/run_handler_local.sh \
  --lock lockfiles/comfy-my-version.lock.json \
  --workflow ./workflows/minimal.json \
  --output base64
```

## Запуск с GCS выводом

```bash
export GCS_BUCKET="my-comfy-bucket"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
export GOOGLE_CLOUD_PROJECT="my-project"

./scripts/run_handler_local.sh \
  --lock lockfiles/comfy-my-version.lock.json \
  --workflow ./workflows/wan_t2i.js \
  --output gcs
```

## Запуск с кастомными переменными окружения

```bash
export COMFY_HOME="/runpod-volume/comfy"
export MODELS_DIR="$COMFY_HOME/models"
export COMFY_VERSION_NAME="my-version"

./scripts/run_handler_local.sh \
  --lock lockfiles/comfy-my-version.lock.json \
  --workflow ./workflows/flux_kontext_dev_basic.js \
  --output base64
```

## Параметры run_handler_local.sh

-   `--lock FILE` — путь к lock-файлу (обязательно)
-   `--workflow FILE` — путь к workflow файлу (обязательно)
-   `--output base64|gcs` — режим вывода (по умолчанию: gcs)

## Переменные окружения для RunPod

```bash
# Основные пути
export COMFY_HOME="/runpod-volume/comfy"
export MODELS_DIR="$COMFY_HOME/models"

# Версия
export COMFY_VERSION_NAME="my-custom-version"

# GCS (для вывода результатов)
export OUTPUT_MODE="gcs"
export GCS_BUCKET="my-comfy-results-bucket"
export GOOGLE_APPLICATION_CREDENTIALS="/runpod-volume/keys/service-account.json"
export GOOGLE_CLOUD_PROJECT="my-gcp-project"
export GCS_PREFIX="comfy/outputs"
export GCS_RETRIES="3"
export GCS_RETRY_BASE_SLEEP="0.5"
export GCS_PUBLIC="false"
export GCS_SIGNED_URL_TTL="3600"
export GCS_VALIDATE="true"

# Lock файл (альтернатива COMFY_VERSION_NAME)
export LOCK_PATH="/runpod-volume/lockfiles/comfy-my-version.lock.json"

# HF токены для приватных моделей
export HF_TOKEN="hf_xxxxxxxxxxxxxxxxxxxxxxxxx"

# Civitai токены
export CIVITAI_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxx"
```

## Запуск ComfyUI напрямую на RunPod

```bash
# Активация окружения
cd /runpod-volume/comfy
source .venv/bin/activate

# Запуск с web UI
python ComfyUI/main.py --listen 0.0.0.0 --port 8188

# Или без web UI (headless)
python ComfyUI/main.py --headless
```

## Запуск конкретного workflow через API

```bash
# Активация окружения
cd /runpod-volume/comfy
source .venv/bin/activate

# Запуск workflow через API
curl -X POST "http://localhost:8188/prompt" \
  -H "Content-Type: application/json" \
  -d @/path/to/workflow.json
```

## Мониторинг запуска

```bash
# Проверка логов
tail -f /runpod-volume/comfy/ComfyUI/comfy.log

# Проверка процессов
ps aux | grep python

# Проверка GPU использования
nvidia-smi

# Проверка памяти
free -h
vmstat 1
```

## Запуск в фоне на RunPod

```bash
# Запуск ComfyUI в фоне
cd /runpod-volume/comfy
source .venv/bin/activate
nohup python ComfyUI/main.py --listen 0.0.0.0 --port 8188 > comfy.log 2>&1 &

# Получение PID
echo $! > comfy.pid

# Проверка статуса
kill -0 $(cat comfy.pid) && echo "Running" || echo "Stopped"
```

## Остановка ComfyUI

```bash
# Graceful остановка
kill $(cat comfy.pid)

# Force остановка
kill -9 $(cat comfy.pid)

# Очистка
rm -f comfy.pid
```

## Запуск с Jupyter notebook

```bash
# Установка jupyter
cd /runpod-volume/comfy
source .venv/bin/activate
pip install jupyter notebook

# Запуск
jupyter notebook --ip 0.0.0.0 --port 8888 --no-browser --allow-root
```

## Тестирование установки

```bash
# Быстрый тест импортов
cd /runpod-volume/comfy
source .venv/bin/activate

python -c "
import torch
print('PyTorch version:', torch.__version__)
print('CUDA available:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('CUDA version:', torch.version.cuda)
    print('GPU count:', torch.cuda.device_count())
    print('Current GPU:', torch.cuda.current_device())
    print('GPU name:', torch.cuda.get_device_name())
"

# Тест ComfyUI импорта
python -c "
import sys
sys.path.append('ComfyUI')
try:
    import comfy.model_management
    print('ComfyUI import: OK')
except Exception as e:
    print('ComfyUI import: FAILED -', e)
"
```

## Запуск с кастомными настройками

```bash
# Создание extra_model_paths.yaml для дополнительных путей
cat > extra_model_paths.yaml << EOF
comfyui:
    base_path: /runpod-volume/comfy
    checkpoints: models/checkpoints
    clip: models/clip
    clip_vision: models/clip_vision
    configs: models/configs
    controlnet: models/controlnet
    diffusion_models: models/diffusion_models
    embeddings: models/embeddings
    loras: models/loras
    unet: models/unet
    vae: models/vae
    photomaker: models/photomaker
    upscale_models: models/upscale_models
EOF

# Запуск с extra_model_paths
cd /runpod-volume/comfy
source .venv/bin/activate
python ComfyUI/main.py --extra-model-paths-config extra_model_paths.yaml --listen 0.0.0.0 --port 8188
```

## Профилирование производительности

```bash
# Установка py-spy для профилирования
pip install py-spy

# Профилирование ComfyUI
py-spy top --pid $(pgrep -f "python ComfyUI/main.py")

# Memory profiling
pip install memory-profiler
python -m memory_profiler ComfyUI/main.py --listen 0.0.0.0 --port 8188
```

## Логирование и отладка

```bash
# Детальное логирование
export COMFY_LOG_LEVEL="DEBUG"

# Запуск с логированием в файл
cd /runpod-volume/comfy
source /workspace/ComfyUI/.venv/bin/activate
python ComfyUI/main.py --listen 0.0.0.0 --port 8188 2>&1 | tee comfy-debug.log

# Просмотр логов в реальном времени
tail -f comfy-debug.log | grep -E "(ERROR|WARNING|INFO)"
```

## Автоматизация запуска на RunPod

```bash
#!/bin/bash
# runpod_start.sh

# Настройка переменных окружения
export COMFY_HOME="/runpod-volume/comfy"
export MODELS_DIR="$COMFY_HOME/models"
export COMFY_VERSION_NAME="production-v1"

# Настройка GCS
export GCS_BUCKET="my-comfy-production"
export GOOGLE_APPLICATION_CREDENTIALS="/runpod-volume/keys/prod-service-account.json"

# Клонирование версии если нужно
if [ ! -d "$COMFY_HOME" ]; then
    /workspace/scripts/clone_version.sh \
        --lock /workspace/lockfiles/comfy-production-v1.lock.json \
        --target "$COMFY_HOME"
fi

# Запуск ComfyUI
cd "$COMFY_HOME"
source .venv/bin/activate

# Запуск в фоне с мониторингом
nohup python ComfyUI/main.py --headless > comfy.log 2>&1 &
echo $! > comfy.pid

# Ожидание готовности
sleep 10

# Проверка здоровья
curl -f http://localhost:8188/system_stats || exit 1

echo "ComfyUI started successfully"
```
