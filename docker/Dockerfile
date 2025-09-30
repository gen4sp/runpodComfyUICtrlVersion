# syntax=docker/dockerfile:1

# Используем тот же базовый образ что и в Pod для совместимости окружений
FROM runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COMFY_HOME=/runpod-volume/ComfyUI \
    MODELS_DIR=/runpod-volume/models

WORKDIR /app

# Базовый образ runpod/pytorch уже содержит git, curl, build-essential, libgl1, libglib2.0-0
# Дополнительных системных пакетов не требуется

# Копируем скрипты и handler внутрь образа
COPY scripts/ /app/scripts/
COPY rp_handler/ /app/rp_handler/
# Версии теперь передаются только через payload (version_id); каталог versions может быть смонтирован при необходимости
COPY versions/ /app/versions/

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


