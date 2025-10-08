# Пересборка Docker образа для RunPod Serverless

## Быстрая команда

```bash
# Собрать и загрузить с новым тегом
docker build -t gen4sp/runpod-pytorch-serverless:v15 -f docker/Dockerfile .
docker push gen4sp/runpod-pytorch-serverless:v15
```

## Что изменилось

### Исправление "context deadline exceeded"

**Проблема:** Контейнер не успевал стартовать из-за задержки монтирования Network Volume.

**Решение:**

-   `entrypoint.sh` теперь ждёт до 60 секунд монтирования `/runpod-volume`
-   При отсутствии volume контейнер завершается с понятной ошибкой

### Структура volume

Убедитесь что на Network Volume размещены:

```
/runpod-volume/
├── runpodComfyUICtrlVersion/
│   ├── scripts/
│   ├── rp_handler/
│   ├── versions/
│   ├── models/
│   └── nodes/
├── ComfyUI/          # создастся автоматически при первом запуске
├── models/           # кеш моделей
└── gc-service-account-key.json  # для GCS (опционально)
```

## После пересборки

1. Обновите Serverless Template в RunPod:

    - Image: `gen4sp/runpod-pytorch-serverless:v13`
    - Убедитесь что Network Volume подключён
    - Mount Path: `/runpod-volume`

2. Проверьте логи первого запуска:
    ```
    [INFO] Проверка доступности volume...
    [OK] Volume /runpod-volume успешно примонтирован
    [INFO] Смонтирована директория scripts...
    [INFO] Starting serverless adapter
    ```

## Альтернатива: multi-platform build

Если нужен для ARM/AMD:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t gen4sp/runpod-pytorch-serverless:v13 \
  -f docker/Dockerfile \
  --push .
```

## Документация

-   Полная документация: [docs/runpod.md](../docs/runpod.md)
-   Решение проблем: [docs/runpod.md#диагностика](../docs/runpod.md#диагностика)
