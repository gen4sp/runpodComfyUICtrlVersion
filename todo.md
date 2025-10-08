sageattention - добавить для wan22

## ✅ Добавлена поддержка передачи входных изображений (input_images)

-   ✅ Реализована загрузка изображений по URL в `rp_handler/serverless.py`
-   ✅ Добавлена функция `_download_input_images()` для скачивания изображений в `{COMFY_HOME}/input/`
-   ✅ Обновлена документация `docs/runpod.md` с примерами использования
-   ✅ Добавлены best practices для работы с GCS signed URLs

**Формат payload:**

```json
{
    "input": {
        "version_id": "...",
        "workflow": {...},
        "input_images": {
            "img1.png": "https://example.com/image.jpg",
            "img2.png": "https://storage.googleapis.com/bucket/image2.png"
        }
    }
}
```

## Исправлено "context deadline exceeded" (v13)

-   ✅ Добавлено ожидание монтирования volume в entrypoint.sh (60s timeout)
-   ✅ Улучшено логирование старта контейнера
-   ✅ Создан скрипт быстрой пересборки: scripts/rebuild_serverless.sh
-   ✅ Добавлена документация: docker/QUICKFIX.md, docker/REBUILD.md
-   ✅ Обновлена docs/runpod.md с разделом диагностики
