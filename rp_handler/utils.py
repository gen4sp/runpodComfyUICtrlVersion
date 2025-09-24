#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple


def log_info(msg: str) -> None:
    """Логирование информационных сообщений."""
    print(f"[INFO] {msg}")


def log_warn(msg: str) -> None:
    """Логирование предупреждений."""
    print(f"[WARN] {msg}")


def log_error(msg: str) -> None:
    """Логирование ошибок."""
    print(f"[ERROR] {msg}")


def run_command(
    cmd: List[str], 
    cwd: Optional[str] = None, 
    env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None
) -> Tuple[int, str, str]:
    """
    Выполнить команду и вернуть код возврата, stdout и stderr.
    
    Args:
        cmd: Команда для выполнения
        cwd: Рабочая директория
        env: Переменные окружения
        timeout: Таймаут выполнения в секундах
        
    Returns:
        Tuple[код_возврата, stdout, stderr]
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired as e:
        log_error(f"Command timed out after {timeout} seconds: {' '.join(cmd)}")
        return -1, "", str(e)
    except Exception as e:
        log_error(f"Command failed: {' '.join(cmd)} - {e}")
        return -1, "", str(e)


def expand_env_vars(path: str, extra_env: Optional[Dict[str, str]] = None) -> str:
    """
    Развернуть переменные окружения в пути.
    
    Args:
        path: Путь с переменными окружения
        extra_env: Дополнительные переменные окружения
        
    Returns:
        Путь с развернутыми переменными
    """
    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)
        # Явные подстановки, затем общее развертывание
        expanded = path.replace("$COMFY_HOME", extra_env.get("COMFY_HOME", ""))
        expanded = expanded.replace("$MODELS_DIR", extra_env.get("MODELS_DIR", ""))
        return os.path.expandvars(expanded)
    return os.path.expandvars(path)


def get_env_bool(name: str, default: bool = False) -> bool:
    """
    Получить булево значение из переменной окружения.
    
    Args:
        name: Имя переменной окружения
        default: Значение по умолчанию
        
    Returns:
        Булево значение
    """
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def validate_required_path(path: str, description: str) -> None:
    """
    Проверить, что путь существует.
    
    Args:
        path: Путь для проверки
        description: Описание пути для сообщения об ошибке
        
    Raises:
        RuntimeError: Если путь не существует
    """
    if not os.path.exists(path):
        raise RuntimeError(f"{description} not found: {path}")


def ensure_directory(path: str) -> None:
    """
    Создать директорию, если она не существует.
    
    Args:
        path: Путь к директории
    """
    os.makedirs(path, exist_ok=True)
