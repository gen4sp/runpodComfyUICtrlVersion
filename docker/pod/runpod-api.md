# Запуск Pod с Docker через RunPod API

Поскольку в веб-интерфейсе RunPod нет возможности указать `--privileged`, используйте API для создания Pod.

## Способ 1: GraphQL API

### Создание Pod с privileged через API

```bash
export RUNPOD_API_KEY="your-api-key-here"

curl -X POST https://api.runpod.io/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -d '{
    "query": "mutation { podFindAndDeployOnDemand( input: { cloudType: ALL gpuTypeId: \"NVIDIA RTX A5000\" name: \"my-docker-pod\" imageName: \"gen4sp/runpod-pytorch-docker:latest\" dockerArgs: \"--privileged\" containerDiskInGb: 50 volumeInGb: 100 ports: \"8888/http,8188/http\" env: [ { key: \"JUPYTER_TOKEN\", value: \"\" } ] } ) { id imageName env machineId machine { podHostId } } }"
  }'
```

### Параметры:

-   `gpuTypeId`: ID типа GPU (см. список ниже)
-   `dockerArgs`: `"--privileged"` - **КЛЮЧЕВОЙ ПАРАМЕТР**
-   `containerDiskInGb`: размер диска контейнера
-   `volumeInGb`: размер постоянного volume
-   `ports`: открываемые порты
-   `imageName`: `gen4sp/runpod-pytorch-docker:latest`

### Популярные GPU IDs:

```
NVIDIA RTX A5000    -> NVIDIA RTX A5000
NVIDIA RTX A6000    -> NVIDIA RTX A6000
NVIDIA A40          -> NVIDIA A40
NVIDIA A100 80GB    -> NVIDIA A100 80GB PCIe
NVIDIA H100 80GB    -> NVIDIA H100 80GB HBM3
```

Полный список: https://graphql-spec.runpod.io/#definition-GpuTypeId

## Способ 2: Python SDK

### Готовый скрипт

Используйте готовый скрипт [create_pod.py](./create_pod.py):

```bash
# Установите SDK
pip install runpod

# Установите API ключ
export RUNPOD_API_KEY="your-api-key-here"

# Запустите скрипт
./create_pod.py --name my-docker-pod --gpu "NVIDIA RTX A5000"

# Или с параметрами
./create_pod.py \
  --name my-docker-pod \
  --gpu "NVIDIA RTX A5000" \
  --container-disk 50 \
  --volume 100
```

### Вручную через Python

```python
import runpod

runpod.api_key = "your-api-key-here"

pod = runpod.create_pod(
    name="my-docker-pod",
    image_name="gen4sp/runpod-pytorch-docker:latest",
    gpu_type_id="NVIDIA RTX A5000",
    docker_args="--privileged",  # ← ВАЖНО!
    container_disk_in_gb=50,
    volume_in_gb=100,
    ports="8888/http,8188/http",
    env={
        "JUPYTER_TOKEN": "",
        "JUPYTER_PASSWORD": ""
    }
)

print(f"Pod ID: {pod['id']}")
print(f"Pod URL: https://runpod.io/console/pods/{pod['id']}")
```

## Способ 3: Обращение в поддержку RunPod

Напишите в поддержку RunPod и попросите:

1. Добавить возможность указывать Docker arguments в веб-интерфейсе
2. Или создать Custom Template с `--privileged` для вас

Support: https://runpod.io/support

## Способ 4: Использовать Template с API

Сначала создайте Template через API:

```bash
curl -X POST https://api.runpod.io/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -d '{
    "query": "mutation { saveTemplate( input: { name: \"PyTorch + Docker\" imageName: \"gen4sp/runpod-pytorch-docker:latest\" dockerArgs: \"--privileged\" containerDiskInGb: 50 volumeInGb: 100 ports: \"8888/http,8188/http\" env: [ { key: \"JUPYTER_TOKEN\", value: \"\" } ] isServerless: false } ) { id name } }"
  }'
```

Затем используйте этот Template в веб-интерфейсе RunPod.

## Проверка после запуска

После запуска Pod подключитесь через SSH или Jupyter и проверьте:

```bash
# Проверка Docker
docker info
docker ps

# Запуск тестового контейнера
docker run hello-world
```

Если Docker работает - вы увидите сообщение от hello-world контейнера.

## Альтернатива: Работа без Docker-in-Docker

Если Docker не критичен, используйте переменную окружения:

```bash
SKIP_DOCKER=true
```

Тогда контейнер запустится только с Jupyter, без попыток запустить Docker.
