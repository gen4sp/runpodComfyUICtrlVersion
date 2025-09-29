#!/usr/bin/env bash
# Скрипт для сборки и публикации Docker образа

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="gen4sp/runpod-pytorch-docker"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "==> Сборка образа: ${IMAGE_NAME}:${IMAGE_TAG}"

# Проверка наличия buildx
if ! docker buildx version >/dev/null 2>&1; then
  echo "ERROR: docker buildx не установлен" >&2
  exit 1
fi

# Сборка для amd64 (платформа RunPod)
docker buildx build \
  --platform linux/amd64 \
  -t "${IMAGE_NAME}:${IMAGE_TAG}" \
  --load \
  "${SCRIPT_DIR}"

echo "==> Образ собран: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "Для публикации в registry используйте:"
echo "  docker push ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "Или пересоберите с --push:"
echo "  docker buildx build --platform linux/amd64 -t ${IMAGE_NAME}:${IMAGE_TAG} --push ${SCRIPT_DIR}"
