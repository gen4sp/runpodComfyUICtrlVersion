# syntax=docker/dockerfile:1

# Используем тот же базовый образ что и в Pod для совместимости окружений
FROM runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04

# COMFY_USE_SYSTEM_PYTHON=1 принудительно использует системный Python из контейнера,
# т.к. venv созданный в другом окружении (Pod) не portable и будет ломаться в serverless контейнере
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COMFY_HOME=/runpod-volume/ComfyUI \
    MODELS_DIR=/runpod-volume/models \
    COMFY_USE_SYSTEM_PYTHON=1 \
    GOOGLE_APPLICATION_CREDENTIALS=/runpod-volume/gc-service-account-key.json \
    GCS_BUCKET=hyper_tv \
    OUTPUT_MODE=gcs \
    GOOGLE_CLOUD_PROJECT=lia-profiler \
    GCS_PREFIX=comfy/outputs


WORKDIR /app

# Базовый образ runpod/pytorch уже содержит git, curl, build-essential, libgl1, libglib2.0-0
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev \
    libpng-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
# Дополнительных системных пакетов не требуется

# Скрипты, handler и версии будут монтированы в /runpod-volume/runpodComfyUICtrlVersion/ в момент запуска

# Создаём директории для COMFY_HOME и моделей
RUN mkdir -p "$COMFY_HOME" "$MODELS_DIR"

RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install \
      pyyaml \
      google-cloud-storage \
      runpod

# Добавляем entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["serverless"]


