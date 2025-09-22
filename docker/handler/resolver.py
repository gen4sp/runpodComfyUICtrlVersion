#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from typing import Dict, List, Optional, Tuple


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def log_error(msg: str) -> None:
    print(f"[ERROR] {msg}")


def run(cmd: List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out.strip(), err.strip()


def expand_env(path: str, extra_env: Optional[Dict[str, str]] = None) -> str:
    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)
        # Explicit substitutions then generic expansion
        expanded = path.replace("$COMFY_HOME", extra_env.get("COMFY_HOME", ""))
        expanded = expanded.replace("$MODELS_DIR", extra_env.get("MODELS_DIR", ""))
        return os.path.expandvars(expanded)
    return os.path.expandvars(path)


def derive_env(models_dir: Optional[str]) -> Dict[str, str]:
    env: Dict[str, str] = {}
    comfy_home = os.environ.get("COMFY_HOME")
    if comfy_home:
        env["COMFY_HOME"] = comfy_home
    else:
        env["COMFY_HOME"] = str((pathlib.Path("/opt/comfy")).resolve())
    env["MODELS_DIR"] = models_dir or str(pathlib.Path(env["COMFY_HOME"]) / "models")
    return env


def load_lock(path: Optional[str]) -> Dict[str, object]:
    if not path:
        log_warn("No lock file path provided; continuing with minimal setup")
        return {}
    lock_path = pathlib.Path(path)
    if not lock_path.exists():
        log_warn(f"Lock file not found: {lock_path}")
        return {}
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    return data


def install_python_packages(lock: Dict[str, object], verbose: bool) -> None:
    python = lock.get("python") if isinstance(lock, dict) else None
    if not isinstance(python, dict):
        log_warn("No python section in lock; skipping packages install")
        return
    packages = python.get("packages")
    if not isinstance(packages, list) or not packages:
        log_warn("Empty python.packages; skipping")
        return
    # Compose pip install args from lock
    args: List[str] = [sys.executable, "-m", "pip", "install"]
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
    code, out, err = run(args)
    if code != 0:
        log_warn(f"pip install returned {code}: {err}")
    elif verbose:
        log_info(out)


def verify_and_fetch_models(lock_path: Optional[str], env: Dict[str, str], verbose: bool) -> None:
    if not lock_path:
        return
    script_path = pathlib.Path("/app/scripts/verify_models.py")
    if not script_path.exists():
        log_warn("verify_models.py not found in image; skipping model verification")
        return
    args = [sys.executable, str(script_path), "--lock", str(lock_path), "--models-dir", env["MODELS_DIR"], "--verbose"]
    code, out, err = run(args)
    if code != 0:
        log_warn(f"verify_models failed ({code}): {err}")
    elif verbose:
        log_info(out)


def apply_lock_and_prepare(lock_path: Optional[str], models_dir: Optional[str], verbose: bool) -> None:
    env = derive_env(models_dir=models_dir)
    lock = load_lock(lock_path)
    # 1) Установить python пакеты согласно lock
    install_python_packages(lock, verbose=verbose)
    # 2) Проверить/восстановить модели
    if lock_path:
        verify_and_fetch_models(lock_path=lock_path, env=env, verbose=verbose)


