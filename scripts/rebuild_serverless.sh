#!/usr/bin/env bash
# Быстрая пересборка и деплой serverless образа
set -Eeuo pipefail

# Цвета для логов
BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Параметры по умолчанию
IMAGE_NAME="${DOCKER_IMAGE:-gen4sp/runpod-pytorch-serverless}"
IMAGE_TAG="${DOCKER_TAG:-v13}"
FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

usage() {
  cat <<EOF
Пересборка и загрузка serverless образа в Docker Hub

Usage:
  $0 [OPTIONS]

Options:
  --tag TAG         Тег образа (default: v13)
  --name NAME       Имя образа (default: gen4sp/runpod-pytorch-serverless)
  --no-cache        Пересобрать без кеша
  --push            Автоматически загрузить в registry
  -h, --help        Показать помощь

Environment:
  DOCKER_IMAGE      Переопределить имя образа
  DOCKER_TAG        Переопределить тег

Examples:
  # Только собрать
  $0

  # Собрать и загрузить
  $0 --push

  # С новым тегом
  $0 --tag v14 --push

  # Без кеша
  $0 --no-cache --push
EOF
}

NO_CACHE=""
AUTO_PUSH=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      IMAGE_TAG="$2"
      FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
      shift 2
      ;;
    --name)
      IMAGE_NAME="$2"
      FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
      shift 2
      ;;
    --no-cache)
      NO_CACHE="--no-cache"
      shift
      ;;
    --push)
      AUTO_PUSH=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

cd "$ROOT_DIR"

echo -e "${BLUE}=== Пересборка Docker образа ===${NC}"
echo -e "${BLUE}Образ:${NC} ${FULL_IMAGE}"
echo -e "${BLUE}Опции:${NC} ${NO_CACHE:-использовать кеш}"
echo ""

# Сборка
echo -e "${BLUE}[1/2] Сборка образа...${NC}"
docker build $NO_CACHE -t "${FULL_IMAGE}" -f docker/Dockerfile .

echo ""
echo -e "${GREEN}✓ Образ собран успешно: ${FULL_IMAGE}${NC}"
echo ""

# Push (если запрошен)
if [ "$AUTO_PUSH" = true ]; then
  echo -e "${BLUE}[2/2] Загрузка в registry...${NC}"
  docker push "${FULL_IMAGE}"
  echo ""
  echo -e "${GREEN}✓ Образ загружен: ${FULL_IMAGE}${NC}"
else
  echo -e "${YELLOW}Для загрузки в registry выполните:${NC}"
  echo "  docker push ${FULL_IMAGE}"
fi

echo ""
echo -e "${GREEN}=== Готово! ===${NC}"
echo ""
echo "Следующие шаги:"
echo "  1. Обновите Serverless Template в RunPod с новым образом:"
echo "     ${FULL_IMAGE}"
echo "  2. Убедитесь что Network Volume подключён (mount: /runpod-volume)"
echo "  3. Проверьте что код размещён на volume:"
echo "     /runpod-volume/runpodComfyUICtrlVersion/{scripts,rp_handler,versions}"
echo ""
echo "Документация: docs/runpod.md"
