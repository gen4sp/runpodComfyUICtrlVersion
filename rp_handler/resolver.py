#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
from typing import Dict, List, Optional, Tuple

from .utils import log_info, log_warn, log_error, run_command, expand_env_vars, validate_required_path


# Функция expand_env удалена, используется expand_env_vars из utils


def derive_env(models_dir: Optional[str]) -> Dict[str, str]:
    """Вычислить переменные окружения для ComfyUI."""
    env: Dict[str, str] = {}
    
    # COMFY_HOME
    comfy_home = os.environ.get("COMFY_HOME")
    if comfy_home:
        env["COMFY_HOME"] = str(pathlib.Path(comfy_home).resolve())
    else:
        env["COMFY_HOME"] = str(pathlib.Path("/opt/comfy").resolve())
    
    # MODELS_DIR
    if models_dir:
        env["MODELS_DIR"] = str(pathlib.Path(models_dir).resolve())
    else:
        env["MODELS_DIR"] = str(pathlib.Path(env["COMFY_HOME"]) / "models")
    
    return env


def load_lock(path: Optional[str]) -> Dict[str, object]:
    """Загрузить lock-файл."""
    if not path:
        log_warn("No lock file path provided; continuing with minimal setup")
        return {}
    
    lock_path = pathlib.Path(path)
    if not lock_path.exists():
        log_warn(f"Lock file not found: {lock_path}")
        return {}
    
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError) as e:
        log_error(f"Failed to load lock file {lock_path}: {e}")
        return {}


def _select_python_executable() -> str:
    # Предпочитаем "python3", затем "python", затем sys.executable
    for cand in ("python3", "python"):
        found = shutil.which(cand)
        if found:
            return found
    return sys.executable


def install_python_packages(lock: Dict[str, object], verbose: bool) -> None:
    """Установить Python пакеты согласно lock-файлу."""
    python = lock.get("python") if isinstance(lock, dict) else None
    if not isinstance(python, dict):
        log_warn("No python section in lock; skipping packages install")
        return
    
    packages = python.get("packages")
    if not isinstance(packages, list) or not packages:
        log_warn("Empty python.packages; skipping")
        return
    
    # Выбор интерпретера Python
    python_interpreter: str = _resolve_python_interpreter(lock, verbose=verbose)

    # Составление аргументов pip install
    args: List[str] = [python_interpreter, "-m", "pip", "install"]
    for item in packages:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        url = item.get("url")
        ver = item.get("version")
        if url:
            args.append(f"{name} @ {url}")
        elif ver:
            args.append(f"{name}=={ver}")
        elif name:
            args.append(name)
    
    if verbose:
        log_info("pip install: " + " ".join(args[4:]))
    
    code, out, err = run_command(args)
    if code != 0:
        log_warn(f"pip install returned {code}: {err}")
    elif verbose:
        log_info(out)


def verify_and_fetch_models(lock_path: Optional[str], env: Dict[str, str], verbose: bool, no_cache: bool = False) -> None:
    """Проверить и загрузить модели согласно lock-файлу."""
    if not lock_path:
        return

    # Поиск скрипта verify_models.py
    possible_paths = [
        pathlib.Path("/app/scripts/verify_models.py"),
        pathlib.Path(__file__).parent.parent / "scripts" / "verify_models.py",
        pathlib.Path.cwd() / "scripts" / "verify_models.py",
    ]

    script_path = None
    for path in possible_paths:
        if path.exists():
            script_path = path
            break

    if not script_path:
        log_warn("verify_models.py not found; skipping model verification")
        return
    
    # Выбор Python интерпретера
    python_exe = _venv_python_from_env() or _select_python_executable()
    
    # Составление аргументов
    args = [
        python_exe, str(script_path), 
        "--lock", str(lock_path), 
        "--models-dir", env["MODELS_DIR"], 
        "--verbose"
    ]
    if not no_cache:
        args.append("--cache")
    
    code, out, err = run_command(args)
    if code != 0:
        log_warn(f"verify_models failed ({code}): {err}")
    elif verbose:
        log_info(out)


def apply_lock_and_prepare(lock_path: Optional[str], models_dir: Optional[str], verbose: bool) -> None:
    """Применить lock-файл и подготовить окружение."""
    env = derive_env(models_dir=models_dir)
    
    # Экспорт переменных в окружение процесса
    os.environ["COMFY_HOME"] = env["COMFY_HOME"]
    os.environ["MODELS_DIR"] = env["MODELS_DIR"]
    
    lock = load_lock(lock_path)
    
    # 1) Установить Python пакеты согласно lock
    install_python_packages(lock, verbose=verbose)
    
    # 2) Проверить/восстановить модели
    if lock_path:
        # Включение кэша только если явно запрошено через env
        use_cache = (
            (os.environ.get("COMFY_ENABLE_CACHE", "").lower() in ("1", "true", "yes"))
            or (os.environ.get("COMFY_CACHE", "").lower() in ("1", "true", "yes"))
        )
        verify_and_fetch_models(lock_path=lock_path, env=env, verbose=verbose, no_cache=(not use_cache))


# ---------------------------- helpers: interpreter ---------------------------- #

def _venv_python_path(venv_dir: pathlib.Path) -> pathlib.Path:
    """Возвращает путь к python внутри venv для текущей платформы."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_python_from_env() -> Optional[str]:
    """Если задан COMFY_HOME и существует venv, вернуть путь к его python."""
    comfy_home = os.environ.get("COMFY_HOME")
    if not comfy_home:
        return None
    venv_dir = pathlib.Path(comfy_home) / ".venv"
    py = _venv_python_path(venv_dir)
    if py.exists() and os.access(str(py), os.X_OK):
        return str(py)
    return None


def _resolve_python_interpreter(lock: Dict[str, object], verbose: bool = False) -> str:
    """Выбрать интерпретер Python для установки пакетов:
    1) python.interpreter из lock, если существует
    2) $COMFY_HOME/.venv/bin/python, если существует; если нет — попытаться создать venv
    3) системный python
    """
    # 1) Из lock
    if isinstance(lock, dict):
        python = lock.get("python")
        if isinstance(python, dict):
            interp = python.get("interpreter")
            if isinstance(interp, str) and interp:
                p = pathlib.Path(interp)
                if p.exists() and os.access(str(p), os.X_OK):
                    if verbose:
                        log_info(f"Using Python interpreter from lock: {interp}")
                    return str(p)

    # 2) Из $COMFY_HOME/.venv
    comfy_home = os.environ.get("COMFY_HOME")
    if comfy_home:
        venv_dir = pathlib.Path(comfy_home) / ".venv"
        venv_python = _venv_python_path(venv_dir)
        if venv_python.exists() and os.access(str(venv_python), os.X_OK):
            if verbose:
                log_info(f"Using Python interpreter from venv: {venv_python}")
            return str(venv_python)
        # Попробуем создать venv, если директории нет или нет python внутри
        try:
            base_py = _select_python_executable()
            if verbose:
                log_info(f"Creating venv at {venv_dir} using {base_py}")
            venv_dir.parent.mkdir(parents=True, exist_ok=True)
            code, out, err = run([base_py, "-m", "venv", str(venv_dir)])
            if code == 0 and venv_python.exists():
                if verbose:
                    log_info(f"Venv created: {venv_python}")
                return str(venv_python)
            else:
                log_warn(f"Failed to create venv at {venv_dir}: {err or out}")
        except Exception as e:
            log_warn(f"Exception while creating venv at {venv_dir}: {e}")

    # 3) Системный python
    sys_py = _select_python_executable()
    if verbose:
        log_info(f"Using system Python interpreter: {sys_py}")
    return sys_py



