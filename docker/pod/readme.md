# RunPod Docker-in-Docker образ

Образ для RunPod (обычный pod, не serverless) с поддержкой Docker внутри контейнера.

## Особенности

-   Базируется на `runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04`
-   Включает Docker daemon (Docker-in-Docker)
-   Сохраняет все функции оригинального образа (Jupyter, SSH и т.д.)
-   Порты: 8888 (Jupyter), 8188 (ComfyUI)

## Сборка образа

```bash
# Локальная сборка
cd /Users/gen4/Gits/Research/RunPod/runpodComfyuiVersionControl/docker/pod
docker build -t gen4sp/runpod-pytorch-docker:latest .

# Сборка и push в registry (multi-platform)
docker buildx build --platform linux/amd64 \
  -t gen4sp/runpod-pytorch-docker:latest \
  --push .
```

## Запуск на RunPod

### Настройка Pod

⚠️ **ВАЖНО**: Docker-in-Docker требует `--privileged` флаг, который **недоступен в веб-интерфейсе RunPod**.

**Два варианта:**

#### Вариант A: Использовать RunPod API (рекомендуется для Docker)

См. подробные инструкции: [runpod-api.md](./runpod-api.md)

Быстрый пример через curl:

```bash
curl -X POST https://api.runpod.io/graphql \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { podFindAndDeployOnDemand(input: { cloudType: ALL gpuTypeId: \"NVIDIA RTX A5000\" name: \"docker-pod\" imageName: \"gen4sp/runpod-pytorch-docker:latest\" dockerArgs: \"--privileged\" containerDiskInGb: 50 volumeInGb: 100 ports: \"8888/http,8188/http\" }) { id } }"}'
```

#### Вариант B: Использовать веб-интерфейс (без Docker)

1. Создайте новый Pod в RunPod
2. Укажите образ: `gen4sp/runpod-pytorch-docker:latest`
3. **Container Start Command**: оставьте пустым
4. **Environment Variables**: добавьте `SKIP_DOCKER=true` (чтобы сразу пропустить попытки запуска Docker)
5. Volume: `/workspace`
6. Ports: `8888` (Jupyter)

**Результат**: Контейнер запустится с Jupyter, но без Docker. Если нужен Docker - используйте Вариант A.

### Переменные окружения

-   `JUPYTER_TOKEN` - токен для Jupyter (пустой по умолчанию)
-   `JUPYTER_PASSWORD` - пароль для Jupyter (пустой по умолчанию)

## Использование Docker внутри Pod

После запуска pod (если использовали Вариант A с API):

```bash
# Проверка Docker
docker ps
docker info

# Запуск тестового контейнера
docker run hello-world

# Пример: запуск ComfyUI в Docker
docker run -d -p 8188:8188 \
  -v /workspace:/workspace \
  comfyui/comfyui:latest
```

Если видите ошибку `Cannot connect to the Docker daemon` - значит контейнер запущен без `--privileged`. См. [runpod-api.md](./runpod-api.md) для решения.

## Режимы работы

1. **Автоматический режим** (по умолчанию):

    - Сначала пытается запустить обычный dockerd (требует privileged)
    - Если не сработало - переключается на rootless dockerd
    - Если ничего не сработало - запускает только Jupyter

2. **С проброшенным docker.sock**:

    - Если примонтировать `/var/run/docker.sock` с хоста
    - Entrypoint автоматически определит и не будет запускать свой dockerd

3. **Ручной режим**:
    - Установите переменную окружения `DOCKER_MODE=manual`
    - Docker не будет запускаться автоматически

## Отладка

Если Docker не запускается:

```bash
# Проверить логи dockerd
cat /var/log/dockerd.log

# Проверить storage driver
docker info | grep "Storage Driver"
```

## Известные ограничения

-   Требует `--privileged` или специальных capabilities для работы dockerd
-   fuse-overlayfs предпочтительнее overlay2 (меньше требований к правам)
-   При использовании overlay2 может потребоваться `--privileged`
