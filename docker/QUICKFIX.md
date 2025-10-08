# 🔧 Быстрое исправление "context deadline exceeded"

## Проблема

```
error creating container: context deadline exceeded
```

## Решение за 3 шага

### 1. Пересоберите образ с исправлением

```bash
cd /Users/gen4/Gits/Research/RunPod/runpodComfyuiVersionControl

# Быстрый способ
./scripts/rebuild_serverless.sh --push

# Или вручную
docker build -t gen4sp/runpod-pytorch-serverless:v13 -f docker/Dockerfile .
docker push gen4sp/runpod-pytorch-serverless:v13
```

### 2. Обновите Serverless Template в RunPod

-   Перейдите в Serverless → Templates → ваш template
-   Измените Image на: `gen4sp/runpod-pytorch-serverless:v13`
-   Сохраните

### 3. Проверьте Network Volume

-   Storage → Network Volumes → убедитесь что volume подключён
-   В Template → Advanced → Network Volume → выберите ваш volume
-   Mount Path должен быть: `/runpod-volume`

### 4. Убедитесь что код на volume

```bash
# Подключитесь к Pod или через SSH проверьте структуру:
ls -la /runpod-volume/runpodComfyUICtrlVersion/

# Должно быть:
# scripts/
# rp_handler/
# versions/
# models/
# nodes/
```

## Что изменилось

**До:** Контейнер пытался стартовать сразу → volume не успевал → timeout

**После:** Контейнер ждёт до 60 секунд монтирования volume → проверяет наличие → стартует

## Логи успешного запуска

```
[INFO] COMFY_HOME=/runpod-volume/ComfyUI
[INFO] MODELS_DIR=/runpod-volume/models
[INFO] Проверка доступности volume...
[OK] Volume /runpod-volume успешно примонтирован
[INFO] Смонтирована директория scripts
[INFO] Смонтирована директория rp_handler
[INFO] Смонтирована директория versions
[INFO] Starting serverless adapter
```

## Если всё ещё не работает

1. Проверьте что volume действительно подключён в Template
2. Попробуйте удалить старый endpoint и создать новый
3. Проверьте статус RunPod: https://status.runpod.io/
4. Убедитесь что используете свежий образ (не кешированный)

## Документация

-   Полная документация: [docs/runpod.md](../docs/runpod.md)
-   Пересборка: [REBUILD.md](REBUILD.md)
