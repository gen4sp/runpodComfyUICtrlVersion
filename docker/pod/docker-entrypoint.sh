#!/usr/bin/env bash
set -euo pipefail

# Проверяем переменную окружения для отключения Docker
if [ "${SKIP_DOCKER:-false}" = "true" ]; then
  echo "[entrypoint] SKIP_DOCKER=true, пропускаю запуск Docker"
  echo "[entrypoint] Запускаю только Jupyter..."
  exec /start.sh
fi

# Если в контейнер проброшен сокет docker-хоста — используем его и не поднимаем свой dockerd
if [ -S /var/run/docker.sock ]; then
  echo "[entrypoint] обнаружен /var/run/docker.sock — пропускаю запуск dockerd"
else
  echo "[entrypoint] /var/run/docker.sock не найден — пытаюсь запустить встроенный dockerd"
  mkdir -p /var/lib/docker

  # Предпочитаем fuse-overlayfs (лучше работает без CAP_SYS_ADMIN), падение на overlay2 как запасной вариант
  storage_driver="fuse-overlayfs"
  if ! command -v fuse-overlayfs >/dev/null 2>&1; then
    storage_driver="overlay2"
  fi

  echo "[entrypoint] Пробуем запустить dockerd с storage driver: ${storage_driver}"

  # Пробуем запустить dockerd без privileged (может сработать с fuse-overlayfs)
  dockerd \
    --host=unix:///var/run/docker.sock \
    --storage-driver="${storage_driver}" \
    --iptables=false \
    --data-root=/var/lib/docker \
    > /var/log/dockerd.log 2>&1 &

  # Ждем готовности dockerd
  for i in $(seq 1 15); do
    echo "Waiting for dockerd to be ready (attempt ${i}/15)..."
    if docker info >/dev/null 2>&1; then
      echo "[entrypoint] ✅ dockerd успешно запустился!"
      break
    fi
    sleep 1
  done

  # Финальная проверка
  if ! docker info >/dev/null 2>&1; then
    echo "" >&2
    echo "============================================" >&2
    echo "WARNING: Docker не запустился" >&2
    echo "============================================" >&2
    echo "" >&2
    echo "Причина: контейнер запущен без --privileged" >&2
    echo "" >&2
    echo "Возможные решения:" >&2
    echo "" >&2
    echo "1. Свяжитесь с поддержкой RunPod и попросите добавить" >&2
    echo "   --privileged к вашему Pod или Template" >&2
    echo "" >&2
    echo "2. Используйте API RunPod для создания Pod с privileged:" >&2
    echo "   https://docs.runpod.io/sdks/graphql/manage-pods" >&2
    echo "" >&2
    echo "3. Используйте образ без Docker-in-Docker:" >&2
    echo "   runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04" >&2
    echo "" >&2
    echo "Логи dockerd (первые 50 строк):" >&2
    head -n 50 /var/log/dockerd.log || true
    echo "" >&2
    echo "============================================" >&2
    echo "Продолжаю запуск БЕЗ Docker..." >&2
    echo "Jupyter будет доступен на порту 8888" >&2
    echo "============================================" >&2
    echo "" >&2
  fi
fi

# Запускаем стандартный старт runpod-образа (jupyter/ssh и т.п.)
exec /start.sh