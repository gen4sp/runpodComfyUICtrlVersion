FROM runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      docker.io \
      iptables \
      fuse-overlayfs \
      ca-certificates \
      curl && \
    rm -rf /var/lib/apt/lists/*

# Создаем необходимые директории
RUN mkdir -p /var/lib/docker /var/log

# Сохраняем оригинальные настройки Jupyter из базового образа
ENV JUPYTER_TOKEN=''
ENV JUPYTER_PASSWORD=''

COPY ./docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Порты: 8888 - Jupyter, 8188 - ComfyUI
EXPOSE 8888
EXPOSE 8188

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]