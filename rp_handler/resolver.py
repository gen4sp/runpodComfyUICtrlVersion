#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

from .utils import log_info, log_warn, log_error, run_command, expand_env_vars
from scripts import verify_models
from rp_handler.cache import (
    models_cache_dir,
    nodes_cache_dir,
    comfy_cache_dir,
    resolved_cache_dir,
)


_MODEL_FETCH_TIMEOUT = int(os.environ.get("COMFY_MODELS_TIMEOUT", "180"))


# Функция expand_env удалена, используется expand_env_vars из utils

class SpecValidationError(Exception):
    """Проблема с валидацией versions/*.json."""


def expand_env(path: str, extra_env: Optional[Dict[str, str]] = None) -> str:
    """Совместимость с тестами: прокси для expand_env_vars."""
    return expand_env_vars(path, extra_env)


def derive_env(models_dir: Optional[str]) -> Dict[str, str]:
    """Вычислить переменные окружения для ComfyUI."""
    env: Dict[str, str] = {}

    comfy_home = os.environ.get("COMFY_HOME")
    if comfy_home:
        env["COMFY_HOME"] = str(pathlib.Path(comfy_home).resolve())
    else:
        env["COMFY_HOME"] = str(pathlib.Path("/opt/comfy").resolve())

    if models_dir:
        env["MODELS_DIR"] = str(pathlib.Path(models_dir).resolve())
    else:
        env["MODELS_DIR"] = str(models_cache_dir())

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


# ------------------------- New version resolve/realize API ------------------------- #

def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def _read_json(path: pathlib.Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_write_json(path: pathlib.Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _slug_from_repo(repo_url: str) -> str:
    # crude slug: last path segment without .git
    tail = repo_url.rstrip("/").split("/")[-1]
    return tail[:-4] if tail.endswith(".git") else tail


def _git_ls_remote(repo: str, ref: Optional[str]) -> Optional[str]:
    # Resolve ref to commit using git ls-remote
    if not ref or not str(ref).strip():
        ref = "HEAD"
    code, out, err = run_command(["git", "ls-remote", repo, str(ref)])
    if code != 0:
        log_warn(f"git ls-remote failed for {repo} {ref}: {err}")
        return None
    # out lines: '<sha>\t<ref>' or single line for HEAD
    for line in out.splitlines():
        parts = line.strip().split("\t", 1)
        if parts and len(parts[0]) == 40:
            return parts[0]
    return None


def _pick_default_comfy_home(version_id: str) -> pathlib.Path:
    # Prefer explicit COMFY_HOME from env
    env_home = os.environ.get("COMFY_HOME")
    if env_home:
        return pathlib.Path(env_home)
    # Prefer RunPod mounts
    for base in (pathlib.Path("/runpod-volume"), pathlib.Path("/workspace")):
        if base.exists() and base.is_dir():
            return base / f"comfy-{version_id}"
    # Fallbacks
    home = os.environ.get("HOME")
    if home:
        return pathlib.Path(home) / f"comfy-{version_id}"
    return pathlib.Path.cwd() / f"comfy-{version_id}"


def _nodes_cache_root() -> pathlib.Path:
    return nodes_cache_dir()


def _comfy_cache_root() -> pathlib.Path:
    return comfy_cache_dir()


def _models_dir_default(comfy_home: pathlib.Path) -> pathlib.Path:
    env_models = os.environ.get("MODELS_DIR")
    if env_models:
        return pathlib.Path(env_models)
    return models_cache_dir()


def _ensure_repo_cache(repo: str, *, offline: bool) -> pathlib.Path:
    cache_root = _comfy_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / _slug_from_repo(repo)

    if not (cache_path / ".git").exists():
        if offline:
            raise RuntimeError(
                f"Offline режим: отсутствует кеш репозитория {repo}, требуется предварительная синхронизация"
            )
        code, out, err = run_command(["git", "clone", repo, str(cache_path)])
        if code != 0:
            raise RuntimeError(f"Не удалось клонировать репозиторий {repo}: {err or out}")
    elif not offline:
        run_command(["git", "-C", str(cache_path), "fetch", "--all", "--tags", "-q"])

    return cache_path


def _checkout_from_cache(
    *,
    cache_repo: pathlib.Path,
    target_repo: pathlib.Path,
    commit: Optional[str],
    offline: bool,
) -> None:
    if target_repo.exists() and not (target_repo / ".git").exists():
        shutil.rmtree(target_repo)

    if not target_repo.exists():
        target_repo.parent.mkdir(parents=True, exist_ok=True)
        clone_args = ["git", "clone", "--shared", str(cache_repo), str(target_repo)]
        code, out, err = run_command(clone_args)
        if code != 0:
            raise RuntimeError(f"Не удалось подготовить рабочую копию ComfyUI: {err or out}")

    # Убедиться, что commit присутствует в кешовом репозитории
    if commit:
        code, _, _ = run_command(["git", "-C", str(cache_repo), "cat-file", "-e", f"{commit}^{{commit}}"])
        if code != 0:
            if offline:
                raise RuntimeError(
                    f"Offline режим: коммит {commit} отсутствует в кешовом репозитории {cache_repo}"
                )
            raise RuntimeError(f"Коммит {commit} отсутствует в кешовом репозитории {cache_repo}")

    # Обновить локальную копию из кеша (без обращения в сеть)
    run_command(["git", "-C", str(target_repo), "remote", "set-url", "origin", str(cache_repo)])
    run_command(["git", "-C", str(target_repo), "fetch", "origin", "--tags", "-q"])

    checkout_target = commit or "HEAD"
    code, out, err = run_command(["git", "-C", str(target_repo), "checkout", "--force", checkout_target])
    if code != 0:
        raise RuntimeError(f"Не удалось переключиться на {checkout_target} в {target_repo}: {err or out}")
    run_command(["git", "-C", str(target_repo), "reset", "--hard", checkout_target])
    run_command(["git", "-C", str(target_repo), "clean", "-fdx"])


def _ensure_symlink(src: pathlib.Path, dst: pathlib.Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.is_symlink() or dst.exists():
            try:
                if dst.is_symlink() and dst.resolve() == src.resolve():
                    return
                dst.unlink()
            except Exception:
                pass
        os.symlink(src, dst, target_is_directory=True)
    except FileExistsError:
        pass


def resolve_version_spec(spec_path: pathlib.Path, offline: bool = False) -> Dict[str, object]:
    """Load versions/<id>.json, resolve missing commits, and return resolved dict.

    Expected spec fields (schema v2):
      - version_id: str
      - comfy: { repo: str, ref?: str, commit?: str }
      - custom_nodes: [ { name?: str, repo: str, ref?: str, commit?: str } ]
      - models: [ { source: str, name?: str, target_subdir?: str } ]
      - env?: dict
      - options?: { offline?: bool, skip_models?: bool }
    """
    spec_raw = _read_json(spec_path)
    spec = validate_version_spec(spec_raw, spec_path)
    version_id = spec["version_id"]
    resolved: Dict[str, object] = {
        "schema_version": 2,
        "version_id": version_id,
        "comfy": {},
        "custom_nodes": [],
        # модели резолвим позже (для удобства обработки target_subdir)
        "models": [],
        "env": spec.get("env", {}),
        "options": {},
        "source_spec": str(spec_path),
    }

    # Options: объединяем CLI/offline параметр и spec.options
    spec_options = spec.get("options", {})
    effective_offline = bool(offline or spec_options.get("offline", False))
    effective_skip_models = bool(spec_options.get("skip_models", False))
    resolved["options"] = {
        "offline": effective_offline,
        "skip_models": effective_skip_models,
    }

    # Comfy
    comfy_in = spec.get("comfy", {})
    repo = comfy_in["repo"]
    ref = comfy_in.get("ref")
    commit = comfy_in.get("commit")
    if not commit:
        if effective_offline:
            log_warn(
                "Offline режим: commit для ComfyUI не указан в спецификации — используем текущее состояние"
            )
        else:
            commit = _git_ls_remote(repo, ref)
            if not commit:
                raise RuntimeError(
                    f"Не удалось резолвить commit для ComfyUI ({repo} {ref or 'HEAD'})"
                )
    resolved["comfy"] = {"repo": repo, "ref": ref, "commit": commit}

    # Custom nodes
    out_nodes: List[Dict[str, Optional[str]]] = []
    for n in spec.get("custom_nodes", []):
        n_repo = n["repo"]
        n_ref = n.get("ref")
        n_commit = n.get("commit")
        n_name = n.get("name") or _slug_from_repo(n_repo)
        if not n_commit:
            if effective_offline:
                log_warn(
                    f"Offline режим: commit не указан для кастом-ноды {n_repo} — пропускаем резолвинг"
                )
            else:
                n_commit = _git_ls_remote(n_repo, n_ref)
                if not n_commit:
                    raise RuntimeError(
                        f"Не удалось резолвить commit для кастом-ноды ({n_repo} {n_ref or 'HEAD'})"
                    )
        out_nodes.append({"name": n_name, "repo": n_repo, "ref": n_ref, "commit": n_commit})
    resolved["custom_nodes"] = out_nodes

    # Models: добавляем target_path на основе target_subdir (если не указан явно)
    models: List[Dict[str, object]] = []
    for m in spec.get("models", []):
        if not isinstance(m, dict):
            continue
        model_entry: Dict[str, object] = dict(m)
        target_path = model_entry.get("target_path") or model_entry.get("path")
        subdir = model_entry.get("target_subdir")
        name = model_entry.get("name") or model_entry.get("source")
        if not target_path:
            # Сформируем путь из MODELS_DIR + target_subdir + name
            if not isinstance(subdir, str) or not subdir.strip():
                log_warn(
                    f"models entry '{name}' не имеет target_path/target_subdir — используем корень MODELS_DIR"
                )
                rel_path = pathlib.Path(str(name or "model"))
            else:
                rel_path = pathlib.Path(subdir.strip()) / str(name or "model")
            model_entry["target_path"] = str(rel_path)
        else:
            model_entry["target_path"] = str(target_path)
        models.append(model_entry)
    resolved["models"] = models

    return resolved


def save_resolved_lock(resolved: Dict[str, object]) -> pathlib.Path:
    version_id = str(resolved.get("version_id") or "version")
    out_path = resolved_cache_dir() / f"{version_id}.lock.json"
    _safe_write_json(out_path, resolved)
    log_info(f"Resolved-lock saved: {out_path}")
    return out_path


def realize_from_resolved(
    resolved: Dict[str, object],
    *,
    target_path: Optional[pathlib.Path] = None,
    models_dir_override: Optional[pathlib.Path] = None,
    wheels_dir: Optional[pathlib.Path] = None,
    offline: bool = False,
) -> Tuple[pathlib.Path, pathlib.Path]:
    """Create/prepare COMFY_HOME based on resolved spec. Returns (comfy_home, models_dir)."""
    version_id = str(resolved.get("version_id") or "version")
    comfy_home = target_path or _pick_default_comfy_home(version_id)
    comfy_home = comfy_home.resolve()
    models_dir = (models_dir_override or _models_dir_default(comfy_home)).resolve()

    # Ensure base dirs
    (comfy_home / "ComfyUI").mkdir(parents=True, exist_ok=True)
    (comfy_home / "ComfyUI" / "custom_nodes").mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    # Clone or update ComfyUI
    comfy = resolved.get("comfy") or {}
    repo = comfy.get("repo") if isinstance(comfy, dict) else None
    commit = comfy.get("commit") if isinstance(comfy, dict) else None
    if not isinstance(repo, str) or not repo:
        raise RuntimeError("Resolved comfy.repo is required")
    repo_dir = comfy_home / "ComfyUI"
    cache_repo = _ensure_repo_cache(repo, offline=offline)
    try:
        _checkout_from_cache(
            cache_repo=cache_repo,
            target_repo=repo_dir,
            commit=commit,
            offline=offline,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"Не удалось подготовить ComfyUI в {repo_dir}: {exc}")

    # Autoinstall ComfyUI requirements
    py = _venv_python_from_env() or _select_python_executable()
    req = repo_dir / "requirements.txt"
    if req.exists() and not offline:
        cmd = [py, "-m", "pip", "install"]
        if wheels_dir:
            cmd.extend(["--no-index", "--find-links", str(wheels_dir)])
        cmd.extend(["-r", str(req)])
        code, out, err = run_command(cmd)
        if code != 0:
            log_warn(f"pip install ComfyUI requirements failed: {err or out}")

    # Custom nodes: clone to cache and symlink
    cache_root = _nodes_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    nodes = resolved.get("custom_nodes") or []
    if isinstance(nodes, list):
        for n in nodes:
            if not isinstance(n, dict):
                continue
            n_repo = str(n.get("repo") or "").strip()
            n_commit = str(n.get("commit") or "").strip()
            n_name = str(n.get("name") or "").strip() or _slug_from_repo(n_repo)
            if not n_repo:
                continue
            cache_name = f"{_slug_from_repo(n_repo)}@{n_commit or 'latest'}"
            cache_path = cache_root / cache_name
            if not (cache_path / ".git").exists():
                if offline:
                    log_warn(
                        f"Offline режим: кэш для ноды {n_repo} не найден ({cache_path}), пропускаем"
                    )
                    continue
                code, out, err = run_command(["git", "clone", n_repo, str(cache_path)])
                if code != 0:
                    log_warn(f"Failed to clone node {n_name}: {err or out}")
                    continue
            if n_commit:
                if not offline:
                    run_command(["git", "-C", str(cache_path), "fetch", "--all", "--tags", "-q"])  # best-effort
                run_command(["git", "-C", str(cache_path), "checkout", n_commit])
            # Symlink into COMFY_HOME
            dst = repo_dir / "custom_nodes" / n_name
            _ensure_symlink(cache_path, dst)
            # Optional: auto-install requirements for node
            if not offline:
                node_req = cache_path / "requirements.txt"
                node_proj = cache_path / "pyproject.toml"
                if node_req.exists():
                    cmd = [py, "-m", "pip", "install"]
                    if wheels_dir:
                        cmd.extend(["--no-index", "--find-links", str(wheels_dir)])
                    cmd.extend(["-r", str(node_req)])
                    code, out, err = run_command(cmd)
                    if code != 0:
                        log_warn(f"pip install for node {n_name} failed: {err or out}")
                elif node_proj.exists():
                    cmd = [py, "-m", "pip", "install"]
                    if wheels_dir:
                        cmd.extend(["--no-index", "--find-links", str(wheels_dir)])
                    cmd.append(str(cache_path))
                    code, out, err = run_command(cmd)
                    if code != 0:
                        log_warn(f"pip install (pyproject) for node {n_name} failed: {err or out}")

    # Models: сверяем с кешем и создаём симлинки
    _prepare_models(
        resolved_models=resolved.get("models") or [],
        models_dir=models_dir,
        offline=offline,
    )

    # Export env
    os.environ["COMFY_HOME"] = str(comfy_home)
    os.environ["MODELS_DIR"] = str(models_dir)
    _write_extra_model_paths(comfy_home=comfy_home, models_dir=models_dir)
    return comfy_home, models_dir


def _prepare_models(*, resolved_models: List[Dict[str, object]], models_dir: pathlib.Path, offline: bool) -> None:
    if not isinstance(resolved_models, list) or not resolved_models:
        return

    offline_effective = bool(offline or verify_models.is_offline_mode())

    for model in resolved_models:
        if not isinstance(model, dict):
            continue

        source = str(model.get("source") or "").strip()
        target_path_raw = str(model.get("target_path") or "").strip()
        checksum_raw = str(model.get("checksum") or "").strip() or None
        name = str(model.get("name") or target_path_raw or "model").strip() or "model"

        if not target_path_raw:
            log_warn(f"models entry '{name}' пропущен: не указан target_path")
            continue

        target_path = pathlib.Path(target_path_raw)
        if target_path.is_absolute():
            target_abs = target_path.resolve()
        else:
            target_abs = (models_dir / target_path).resolve()
        target_abs.parent.mkdir(parents=True, exist_ok=True)

        checksum_algo, checksum_hex = verify_models.parse_checksum(checksum_raw)

        if not source:
            if not target_abs.exists():
                log_warn(f"Модель '{name}' не имеет source и отсутствует по пути {target_abs}")
            elif checksum_hex and checksum_algo:
                actual = verify_models.compute_checksum(str(target_abs), algo=checksum_algo).split(":", 1)[1]
                if actual != checksum_hex:
                    log_warn(
                        f"Модель '{name}' имеет checksum mismatch и не имеет source для переустановки"
                    )
            continue

        cache_path: Optional[pathlib.Path] = None
        try:
            cache_path = verify_models.ensure_cached_model(
                source=source,
                checksum_algo=checksum_algo,
                checksum_hex=checksum_hex,
                name=name,
                offline=offline_effective,
            )
        except RuntimeError as exc:
            if offline_effective:
                log_warn(f"Offline режим: {exc}")
                continue
            log_warn(f"Не удалось подготовить кеш модели '{name}': {exc}")

        if cache_path:
            status = verify_models.ensure_link_from_cache(cache_path, target_abs)
            log_info(f"Модель '{name}': {status} ← {cache_path}")
            continue

        if target_abs.exists():
            if checksum_hex and checksum_algo:
                actual = verify_models.compute_checksum(str(target_abs), algo=checksum_algo).split(":", 1)[1]
                if actual == checksum_hex:
                    continue
                if offline_effective:
                    log_warn(
                        f"Offline режим: checksum mismatch для '{name}' ({target_abs}), оставляю существующий файл"
                    )
                    continue
            else:
                # файл существует, checksum не задан — считаем валидным
                continue

        if offline_effective:
            log_warn(
                f"Offline режим: модель '{name}' отсутствует (или checksum mismatch) и недоступна для загрузки"
            )
            continue

        try:
            with tempfile.TemporaryDirectory(prefix="model_fetch_", dir=str(models_dir)) as tmp_dir:
                tmp_path = verify_models.fetch_to_temp(source, tmp_dir=tmp_dir, timeout=_MODEL_FETCH_TIMEOUT)
                if checksum_hex and checksum_algo:
                    actual = verify_models.compute_checksum(tmp_path, algo=checksum_algo).split(":", 1)[1]
                    if actual != checksum_hex:
                        raise RuntimeError("downloaded checksum mismatch")
                verify_models.atomic_copy(tmp_path, str(target_abs))
                log_info(f"Модель '{name}' загружена: {target_abs}")
        except Exception as exc:
            raise RuntimeError(f"Не удалось загрузить модель '{name}': {exc}") from exc


def _write_extra_model_paths(*, comfy_home: pathlib.Path, models_dir: pathlib.Path) -> None:
    extra_yaml = comfy_home / "extra_model_paths.yaml"
    mapping = {
        "base_path": str(models_dir),
        "checkpoints": str(models_dir / "checkpoints"),
        "clip": str(models_dir / "clip"),
        "clip_vision": str(models_dir / "clip_vision"),
        "configs": str(models_dir / "configs"),
        "controlnet": str(models_dir / "controlnet"),
        "diffusion_models": str(models_dir / "diffusion_models"),
        "embeddings": str(models_dir / "embeddings"),
        "inpaint": str(models_dir / "inpaint"),
        "loras": str(models_dir / "loras"),
        "photomaker": str(models_dir / "photomaker"),
        "text_encoders": str(models_dir / "text_encoders"),
        "unet": str(models_dir / "unet"),
        "upscale_models": str(models_dir / "upscale_models"),
        "vae": str(models_dir / "vae"),
    }
    try:
        lines = ["comfyui:\n"]
        for key in sorted(mapping.keys()):
            lines.append(f"  {key}: {mapping[key]}\n")
        extra_yaml.write_text("".join(lines), encoding="utf-8")
    except Exception as exc:
        log_warn(f"Не удалось записать extra_model_paths.yaml: {exc}")


def validate_version_spec(raw_spec: object, source_path: pathlib.Path) -> Dict[str, object]:
    """Проверить структуру versions/*.json и вернуть нормализованные данные."""

    if not isinstance(raw_spec, dict):
        raise SpecValidationError(f"{source_path}: ожидался объект JSON с полями спецификации")

    schema_version = raw_spec.get("schema_version")
    if schema_version != 2:
        raise SpecValidationError(
            f"{source_path}: поддерживается только schema_version=2 (получено: {schema_version!r})"
        )

    version_id_raw = raw_spec.get("version_id") or raw_spec.get("id")
    if not isinstance(version_id_raw, str) or not version_id_raw.strip():
        raise SpecValidationError(f"{source_path}: поле 'version_id' обязательно и должно быть строкой")
    version_id = version_id_raw.strip()

    comfy_raw = raw_spec.get("comfy")
    if not isinstance(comfy_raw, dict):
        raise SpecValidationError(f"{source_path}: раздел 'comfy' обязателен и должен быть объектом")
    comfy_repo = comfy_raw.get("repo")
    if not isinstance(comfy_repo, str) or not comfy_repo.strip():
        raise SpecValidationError(f"{source_path}: поле 'comfy.repo' обязательно и должно быть строкой")
    comfy_ref = _optional_trimmed_str(comfy_raw.get("ref"), source_path, "comfy.ref")
    comfy_commit = _optional_trimmed_str(comfy_raw.get("commit"), source_path, "comfy.commit")

    custom_nodes_raw = raw_spec.get("custom_nodes", [])
    if custom_nodes_raw is None:
        custom_nodes_raw = []
    if not isinstance(custom_nodes_raw, list):
        raise SpecValidationError(f"{source_path}: 'custom_nodes' должен быть списком")
    custom_nodes: List[Dict[str, Optional[str]]] = []
    for idx, entry in enumerate(custom_nodes_raw):
        if not isinstance(entry, dict):
            raise SpecValidationError(
                f"{source_path}: custom_nodes[{idx}] должен быть объектом (получено {type(entry).__name__})"
            )
        repo_value = entry.get("repo")
        if not isinstance(repo_value, str) or not repo_value.strip():
            raise SpecValidationError(
                f"{source_path}: custom_nodes[{idx}].repo обязателен и должен быть строкой"
            )
        node_ref = _optional_trimmed_str(entry.get("ref"), source_path, f"custom_nodes[{idx}].ref")
        node_commit = _optional_trimmed_str(entry.get("commit"), source_path, f"custom_nodes[{idx}].commit")
        node_name = _optional_trimmed_str(entry.get("name"), source_path, f"custom_nodes[{idx}].name")
        custom_nodes.append(
            {
                "repo": repo_value.strip(),
                "ref": node_ref,
                "commit": node_commit,
                "name": node_name,
            }
        )

    models_raw = raw_spec.get("models", [])
    if models_raw is None:
        models_raw = []
    if not isinstance(models_raw, list):
        raise SpecValidationError(f"{source_path}: 'models' должен быть списком")
    models: List[Dict[str, Optional[str]]] = []
    for idx, entry in enumerate(models_raw):
        if not isinstance(entry, dict):
            raise SpecValidationError(
                f"{source_path}: models[{idx}] должен быть объектом (получено {type(entry).__name__})"
            )
        source_value = entry.get("source")
        if not isinstance(source_value, str) or not source_value.strip():
            raise SpecValidationError(
                f"{source_path}: models[{idx}].source обязателен и должен быть строкой"
            )
        name_value = _optional_trimmed_str(entry.get("name"), source_path, f"models[{idx}].name")
        target_subdir_value = _optional_trimmed_str(
            entry.get("target_subdir"), source_path, f"models[{idx}].target_subdir"
        )
        models.append(
            {
                "source": source_value.strip(),
                "name": name_value,
                "target_subdir": target_subdir_value,
            }
        )

    env_raw = raw_spec.get("env", {})
    if env_raw is None:
        env_raw = {}
    if not isinstance(env_raw, dict):
        raise SpecValidationError(f"{source_path}: 'env' (если задан) должен быть объектом")
    env: Dict[str, str] = {}
    for key, value in env_raw.items():
        if not isinstance(key, str) or not key:
            raise SpecValidationError(f"{source_path}: ключи в env должны быть строками")
        env[key] = "" if value is None else str(value)

    options_raw = raw_spec.get("options", {})
    if options_raw is None:
        options_raw = {}
    if not isinstance(options_raw, dict):
        raise SpecValidationError(f"{source_path}: 'options' (если задан) должен быть объектом")
    allowed_options = {"offline", "skip_models"}
    options: Dict[str, bool] = {}
    for key, value in options_raw.items():
        if key not in allowed_options:
            raise SpecValidationError(f"{source_path}: опция '{key}' не поддерживается для schema v2")
        if isinstance(value, bool):
            options[key] = value
        elif value in ("1", "true", "True", 1):
            options[key] = True
        elif value in ("0", "false", "False", 0):
            options[key] = False
        else:
            raise SpecValidationError(
                f"{source_path}: options.{key} ожидает булево значение (true/false)"
            )

    return {
        "schema_version": 2,
        "version_id": version_id,
        "comfy": {
            "repo": comfy_repo.strip(),
            "ref": comfy_ref,
            "commit": comfy_commit,
        },
        "custom_nodes": custom_nodes,
        "models": models,
        "env": env,
        "options": options,
    }


def _optional_trimmed_str(value: object, source_path: pathlib.Path, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SpecValidationError(f"{source_path}: поле '{field_name}' должно быть строкой")
    trimmed = value.strip()
    return trimmed or None


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
            code, out, err = run_command([base_py, "-m", "venv", str(venv_dir)])
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



