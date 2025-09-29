#!/usr/bin/env python3
"""
Скрипт для создания RunPod с Docker-in-Docker через API.
Требует: pip install runpod
"""

import os
import sys
import runpod


def create_docker_pod(
    name: str = "docker-pod",
    gpu_type: str = "NVIDIA RTX A5000",
    image: str = "gen4sp/runpod-pytorch-docker:latest",
    container_disk_gb: int = 50,
    volume_gb: int = 100,
):
    """
    Создает Pod с поддержкой Docker-in-Docker.
    
    Args:
        name: Имя Pod
        gpu_type: Тип GPU (см. список в runpod-api.md)
        image: Docker образ
        container_disk_gb: Размер диска контейнера
        volume_gb: Размер постоянного volume
    """
    
    # Получаем API ключ из переменной окружения
    api_key = os.getenv("RUNPOD_API_KEY")
    if not api_key:
        print("ERROR: RUNPOD_API_KEY не установлен")
        print("Установите: export RUNPOD_API_KEY='your-key-here'")
        sys.exit(1)
    
    runpod.api_key = api_key
    
    print(f"Создаем Pod '{name}' с Docker-in-Docker...")
    print(f"  GPU: {gpu_type}")
    print(f"  Image: {image}")
    print(f"  Container disk: {container_disk_gb}GB")
    print(f"  Volume: {volume_gb}GB")
    print()
    
    try:
        pod = runpod.create_pod(
            name=name,
            image_name=image,
            gpu_type_id=gpu_type,
            docker_args="--privileged",  # КЛЮЧЕВОЙ ПАРАМЕТР для Docker-in-Docker
            container_disk_in_gb=container_disk_gb,
            volume_in_gb=volume_gb,
            ports="8888/http,8188/http",
            env={
                "JUPYTER_TOKEN": "",
                "JUPYTER_PASSWORD": ""
            }
        )
        
        print("✅ Pod успешно создан!")
        print(f"  Pod ID: {pod['id']}")
        print(f"  URL: https://runpod.io/console/pods/{pod['id']}")
        print()
        print("Подождите 1-2 минуты пока Pod запустится.")
        print("Затем откройте Jupyter на порту 8888 и проверьте Docker:")
        print("  docker info")
        print("  docker run hello-world")
        
    except Exception as e:
        print(f"❌ Ошибка при создании Pod: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Создать RunPod с Docker-in-Docker"
    )
    parser.add_argument(
        "--name",
        default="docker-pod",
        help="Имя Pod (default: docker-pod)"
    )
    parser.add_argument(
        "--gpu",
        default="NVIDIA RTX A5000",
        help="Тип GPU (default: NVIDIA RTX A5000)"
    )
    parser.add_argument(
        "--image",
        default="gen4sp/runpod-pytorch-docker:latest",
        help="Docker образ"
    )
    parser.add_argument(
        "--container-disk",
        type=int,
        default=50,
        help="Размер диска контейнера в GB (default: 50)"
    )
    parser.add_argument(
        "--volume",
        type=int,
        default=100,
        help="Размер volume в GB (default: 100)"
    )
    
    args = parser.parse_args()
    
    create_docker_pod(
        name=args.name,
        gpu_type=args.gpu,
        image=args.image,
        container_disk_gb=args.container_disk,
        volume_gb=args.volume,
    )
