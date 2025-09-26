# syntax=docker/dockerfile:1

# Мультиархитектурный базовый образ Python 3.11 slim
FROM python:3.11-slim AS runtime

ARG COMFY_VERSION_NAME=default

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COMFY_HOME=/opt/comfy \
    MODELS_DIR=/opt/comfy/models \
    COMFY_VERSION_NAME=${COMFY_VERSION_NAME}

WORKDIR /app

# Системные зависимости, необходимые для сборки некоторых пакетов и работы ComfyUI
# (git для клона узлов/репо, curl/ca-certificates, gcc и базовые dev headers при необходимости)
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
      git \
      curl \
      ca-certificates \
      build-essential \
      libgl1 \
      libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Копируем скрипты и handler внутрь образа
COPY scripts/ /app/scripts/
COPY rp_handler/ /app/rp_handler/
COPY versions/ /app/versions/

# Создаём директории для COMFY_HOME и моделей
RUN mkdir -p "$COMFY_HOME" "$MODELS_DIR"

# Устанавливаем зависимости handler (минимальные, без торча).
# При необходимости торч ставится самим resolver в зависимости от lock/окружения.
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install \
      pyyaml \
      google-cloud-storage || true

# Добавляем entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]


