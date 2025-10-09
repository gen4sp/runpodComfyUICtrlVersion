"""Paths and helpers for shared ComfyUI caches."""

from __future__ import annotations

import os
import pathlib
from functools import lru_cache


_CACHE_ROOT_ENV_VARS = (
    "COMFY_CACHE_ROOT",
    "RUNPOD_COMFY_CACHE",
    "COMFY_CACHE",
)

_MODELS_CACHE_ENV = (
    "COMFY_CACHE_MODELS",
    "COMFY_MODELS_CACHE",
)

_NODES_CACHE_ENV = (
    "COMFY_CACHE_NODES",
    "COMFY_NODES_CACHE",
)

_COMFY_CACHE_ENV = (
    "COMFY_CACHE_COMFY",
    "COMFY_CORE_CACHE",
)


def _default_cache_root() -> pathlib.Path:
    base_name = "runpod-comfy"
    # Проверяем оба варианта RunPod volume: /workspace (pod) и /runpod-volume (serverless)
    for volume_path in [pathlib.Path("/workspace"), pathlib.Path("/runpod-volume")]:
        if volume_path.exists() and os.access(str(volume_path), os.W_OK | os.X_OK):
            return (volume_path / "cache" / base_name).resolve()

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return pathlib.Path(xdg).expanduser().resolve() / base_name

    return pathlib.Path.home().expanduser().resolve() / ".cache" / base_name


@lru_cache(maxsize=1)
def cache_root() -> pathlib.Path:
    """Return the base directory for all shared caches."""

    for env_name in _CACHE_ROOT_ENV_VARS:
        value = os.environ.get(env_name)
        if value:
            return pathlib.Path(value).expanduser().resolve()
    return _default_cache_root()


def _ensure_dir(path: pathlib.Path) -> pathlib.Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def models_cache_dir() -> pathlib.Path:
    """Directory with cached model artifacts."""

    for env_name in _MODELS_CACHE_ENV:
        value = os.environ.get(env_name)
        if value:
            return _ensure_dir(pathlib.Path(value).expanduser().resolve())
    return _ensure_dir(cache_root() / "models")


@lru_cache(maxsize=1)
def nodes_cache_dir() -> pathlib.Path:
    """Directory with cached custom nodes checkouts."""

    for env_name in _NODES_CACHE_ENV:
        value = os.environ.get(env_name)
        if value:
            return _ensure_dir(pathlib.Path(value).expanduser().resolve())
    return _ensure_dir(cache_root() / "custom_nodes")


@lru_cache(maxsize=1)
def comfy_cache_dir() -> pathlib.Path:
    """Directory with cached ComfyUI core checkouts."""

    for env_name in _COMFY_CACHE_ENV:
        value = os.environ.get(env_name)
        if value:
            return _ensure_dir(pathlib.Path(value).expanduser().resolve())
    return _ensure_dir(cache_root() / "comfy")


@lru_cache(maxsize=1)
def resolved_cache_dir() -> pathlib.Path:
    """Directory for resolved version locks (metadata only)."""

    return _ensure_dir(cache_root() / "resolved")


__all__ = [
    "cache_root",
    "models_cache_dir",
    "nodes_cache_dir",
    "comfy_cache_dir",
    "resolved_cache_dir",
]


