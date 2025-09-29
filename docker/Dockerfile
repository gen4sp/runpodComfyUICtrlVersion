# syntax=docker/dockerfile:1

# Мультиархитектурный базовый образ Python 3.11 slim
FROM python:3.11-slim AS runtime

#anticashe
ARG BUILD_REV2=<commit> # переменная для антикэша
ENV BUILD_REV2=$BUILD_REV2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COMFY_HOME=/workspace/ComfyUI \
    MODELS_DIR=/workspace/models

WORKDIR /app

# RUN apt-get update -y && \
#     apt-get install -y --no-install-recommends \
#       git \
#       curl \
#       ca-certificates \
#       build-essential \
#       libgl1 \
#       libglib2.0-0 && \
#     rm -rf /var/lib/apt/lists/*

# Копируем скрипты и handler внутрь образа
COPY scripts/ /app/scripts/
COPY rp_handler/ /app/rp_handler/
# Версии теперь передаются только через payload (version_id); каталог versions может быть смонтирован при необходимости
COPY versions/ /app/versions/

# Создаём директории для COMFY_HOME и моделей
RUN mkdir -p "$COMFY_HOME" "$MODELS_DIR"

# RUN python -m pip install --upgrade pip setuptools wheel && \
#     python -m pip install \
#       pyyaml \
#       google-cloud-storage \
#       runpod || true

# Добавляем entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["serverless"]


