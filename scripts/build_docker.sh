#!/usr/bin/env bash
# shellcheck disable=SC1091
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$SCRIPT_DIR/lib/common.sh" ]; then . "$SCRIPT_DIR/lib/common.sh"; fi

usage() {
  cat <<'EOF'
Сборка Docker-образа для serverless-адаптера.

Usage:
  scripts/build_docker.sh [--tag TAG]

Опции:
  --tag TAG        Тег образа (по умолчанию: runpod-comfy:latest)
EOF
}

IMAGE_TAG="runpod-comfy:latest"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      IMAGE_TAG="$2"; shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown arg: $1" >&2; usage; exit 1;;
  esac
done

cd "$ROOT_DIR"
echo "Building image: $IMAGE_TAG (serverless-only)"
docker build --tag "$IMAGE_TAG" -f docker/Dockerfile .
echo "\nDone: $IMAGE_TAG"


