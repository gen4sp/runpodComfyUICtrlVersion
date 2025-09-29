# 🚀 Быстрый старт

## Проблема

В веб-интерфейсе RunPod **нет поля для указания `--privileged`**, который необходим для Docker-in-Docker.

## Решение

### ✅ Вариант 1: Python SDK (самый простой)

```bash
# 1. Установите SDK
pip install runpod

# 2. Получите API ключ в RunPod: Settings → API Keys
export RUNPOD_API_KEY="your-key-here"

# 3. Запустите готовый скрипт
cd docker/pod
./create_pod.py --name my-docker-pod --gpu "NVIDIA RTX A5000"
```

**Результат**: Pod с Docker-in-Docker запустится через 1-2 минуты.

### ✅ Вариант 2: GraphQL API

```bash
export RUNPOD_API_KEY="your-key-here"

curl -X POST https://api.runpod.io/graphql \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { podFindAndDeployOnDemand(input: { cloudType: ALL gpuTypeId: \"NVIDIA RTX A5000\" name: \"docker-pod\" imageName: \"gen4sp/runpod-pytorch-docker:latest\" dockerArgs: \"--privileged\" containerDiskInGb: 50 volumeInGb: 100 ports: \"8888/http,8188/http\" }) { id } }"}'
```

### ⚠️ Вариант 3: Веб-интерфейс (БЕЗ Docker)

Если Docker не нужен - можете использовать веб-интерфейс:

1. Image: `gen4sp/runpod-pytorch-docker:latest`
2. Environment: `SKIP_DOCKER=true`
3. Ports: `8888`

**Результат**: Только Jupyter, Docker работать не будет.

## Проверка после запуска

```bash
# SSH или Jupyter Terminal
docker info
docker run hello-world
```

Если Docker работает - вы увидите информацию о системе и сообщение от hello-world.

## Документация

-   [readme.md](./readme.md) - полная документация
-   [runpod-api.md](./runpod-api.md) - подробно про API
-   [create_pod.py](./create_pod.py) - готовый Python скрипт

## Что внутри образа?

-   Base: `runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04`
-   Docker-in-Docker (требует `--privileged`)
-   Jupyter Notebook (порт 8888)
-   ComfyUI ready (порт 8188)
-   CUDA 12.8.1 + PyTorch 2.8.0

## Нужна помощь?

См. [runpod-api.md](./runpod-api.md) для альтернативных способов запуска.
