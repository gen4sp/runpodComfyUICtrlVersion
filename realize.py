#!/usr/bin/env python3
"""Утилита для подготовки версии ComfyUI внутри docker-образа.

Запуск:
    ./realize.py wan22-fast

Скрипт соберёт docker-образ (по умолчанию из ./docker/Dockerfile),
а затем выполнит scripts/version.py realize внутри контейнера, монтируя
pod-volume хоста в /runpod-volume.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import shutil
from typing import List


DEFAULT_IMAGE = os.environ.get("COMFY_REALIZE_IMAGE", "htv/rpsl-htv:v1")
DEFAULT_CONTEXT = os.environ.get("COMFY_REALIZE_CONTEXT", ".")
DEFAULT_DOCKERFILE = os.environ.get("COMFY_REALIZE_DOCKERFILE", "docker/Dockerfile")


def _print_info(message: str) -> None:
    print(f"[INFO] {message}")


def _print_warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)


def _run(cmd: List[str], *, cwd: pathlib.Path | None = None) -> None:
    _print_info("$ " + " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
    except FileNotFoundError as exc:
        raise SystemExit(f"[ERROR] Не найден исполняемый файл '{cmd[0]}': {exc}") from exc


def _require_executable(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"[ERROR] Не найден исполняемый файл '{name}'. Установите Docker или добавьте его в PATH")


def _resolve_path(base: pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(value)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _detect_volume_path() -> pathlib.Path:
    for candidate in (pathlib.Path("/runpod-volume"), pathlib.Path("/workspace")):
        if candidate.exists():
            resolved = candidate.resolve()
            _print_info(f"Использую volume хоста: {resolved}")
            return resolved
    raise SystemExit("[ERROR] Не найден volume (/runpod-volume или /workspace)")


def build_image(args: argparse.Namespace, context_path: pathlib.Path, dockerfile_path: pathlib.Path) -> None:
    if args.no_build:
        _print_info("Пропускаю docker build (передан --no-build)")
        return

    cmd: List[str] = ["docker", "build", "-t", args.image]
    if args.pull:
        cmd.append("--pull")
    if args.no_cache:
        cmd.append("--no-cache")
    for item in args.build_arg or []:
        cmd.extend(["--build-arg", item])
    cmd.extend(["-f", str(dockerfile_path), str(context_path)])
    _run(cmd)


def run_realize_container(args: argparse.Namespace, image: str, version: str, host_volume: pathlib.Path) -> None:
    container_volume = "/runpod-volume"
    target_path = f"{container_volume}/builds/comfy-{version}"

    cmd: List[str] = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"COMFY_VENV_MODE={args.venv_mode}",
        "-v",
        f"{host_volume}:{container_volume}",
    ]

    if host_volume != pathlib.Path("/workspace"):
        workspace_path = host_volume
    else:
        workspace_path = host_volume

    if workspace_path != container_volume:
        cmd.extend(["-v", f"{host_volume}:/workspace"])

    if args.env:
        for env_value in args.env:
            cmd.extend(["-e", env_value])

    cmd.extend(
        [
            image,
            "scripts/version.py",
            "realize",
            version,
            "--target",
            target_path,
        ]
    )

    if args.models_dir:
        cmd.extend(["--models-dir", args.models_dir])
    if args.offline:
        cmd.append("--offline")
    if args.wheels_dir:
        cmd.extend(["--wheels-dir", args.wheels_dir])

    _run(cmd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Realize версии ComfyUI внутри docker-контейнера")
    parser.add_argument("version", help="Идентификатор версии (versions/<id>.json)")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Имя docker-образа для сборки и запуска")
    parser.add_argument("--context", default=DEFAULT_CONTEXT, help="Контекст docker build (по умолчанию репозиторий)")
    parser.add_argument("--dockerfile", default=DEFAULT_DOCKERFILE, help="Путь к Dockerfile (относительно контекста)")
    parser.add_argument("--no-build", action="store_true", help="Пропустить docker build")
    parser.add_argument("--pull", action="store_true", help="Добавить --pull к docker build")
    parser.add_argument("--no-cache", action="store_true", help="Добавить --no-cache к docker build")
    parser.add_argument("--build-arg", action="append", help="Дополнительные --build-arg key=value")
    parser.add_argument("--venv-mode", default=os.environ.get("COMFY_VENV_MODE", "copies"), help="COMFY_VENV_MODE для контейнера (copies|symlinks)")
    parser.add_argument("--env", action="append", help="Дополнительные переменные окружения для docker run (формат KEY=VALUE)")
    parser.add_argument("--models-dir", help="Проброс --models-dir в scripts/version.py")
    parser.add_argument("--wheels-dir", help="Проброс --wheels-dir в scripts/version.py")
    parser.add_argument("--offline", action="store_true", help="Запустить realize c --offline")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = pathlib.Path(__file__).resolve().parent
    context_path = _resolve_path(repo_root, args.context)
    dockerfile_path = _resolve_path(context_path, args.dockerfile)

    _require_executable("docker")

    _print_info(f"Сборка образа {args.image}")
    build_image(args, context_path, dockerfile_path)

    host_volume = _detect_volume_path()

    _print_info(f"Подготовка версии {args.version}")
    run_realize_container(args, args.image, args.version, host_volume)
    _print_info("Готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


