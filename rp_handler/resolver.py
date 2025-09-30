#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
from typing import Dict, List, Optional, Set, Tuple

from .utils import log_info, log_warn, log_error, run_command, expand_env_vars
from scripts import verify_models
from rp_handler.cache import (
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
        env["COMFY_HOME"] = str(pathlib.Path("/runpod-volume/ComfyUI").resolve())

    if models_dir:
        env["MODELS_DIR"] = str(pathlib.Path(models_dir).resolve())
    else:
        env["MODELS_DIR"] = str(pathlib.Path("/runpod-volume/models").resolve())

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
    env_home_raw = os.environ.get("COMFY_HOME")
    default_env_home = "/runpod-volume/ComfyUI"

    if env_home_raw:
        env_home = pathlib.Path(env_home_raw)
        # Пользовательский COMFY_HOME имеет приоритет, кроме случая значения по умолчанию
        if env_home_raw.strip() and env_home_raw.strip() != default_env_home:
            return env_home

    runpod_volume = pathlib.Path("/runpod-volume")
    if runpod_volume.exists() and os.access(str(runpod_volume), os.W_OK | os.X_OK):
        builds_root = runpod_volume / "builds"
        return (builds_root / f"comfy-{version_id}").resolve()

    # Если runpod-volume недоступен, используем env-значение (даже дефолтное)
    if env_home_raw:
        return pathlib.Path(env_home_raw)

    default_home = pathlib.Path(default_env_home)
    if default_home.parent.exists():
        return default_home

    home = os.environ.get("HOME")
    if home:
        return pathlib.Path(home).expanduser() / f"comfy-{version_id}"

    return pathlib.Path.cwd() / f"comfy-{version_id}"


def _nodes_cache_root() -> pathlib.Path:
    return nodes_cache_dir()


def _comfy_cache_root() -> pathlib.Path:
    return comfy_cache_dir()


def _models_dir_default(comfy_home: pathlib.Path) -> pathlib.Path:
    """Определяет общий MODELS_DIR на volume (одинаковый для всех версий)."""
    env_models = os.environ.get("MODELS_DIR")
    if env_models:
        return pathlib.Path(env_models)
    
    # Попытка определить volume root
    # Serverless: /runpod-volume
    runpod_volume = pathlib.Path("/runpod-volume")
    if runpod_volume.exists() and os.access(str(runpod_volume), os.R_OK):
        return runpod_volume / "models"
    
    # Fallback: рядом с comfy_home
    if comfy_home.parts[:2] == ("/", "runpod-volume"):
        return comfy_home.parent / "models"
    
    return comfy_home / "models"


def _ensure_repo_cache(repo: str, *, offline: bool) -> pathlib.Path:
    cache_root = _comfy_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / _slug_from_repo(repo)

    if not (cache_path / ".git").exists():
        log_info(f"[resolver] репозиторий {repo} отсутствует в кешe, клонирую в {cache_path}")
        if offline:
            raise RuntimeError(
                f"Offline режим: отсутствует кеш репозитория {repo}, требуется предварительная синхронизация"
            )
        code, out, err = run_command(["git", "clone", repo, str(cache_path)])
        if code != 0:
            raise RuntimeError(f"Не удалось клонировать репозиторий {repo}: {err or out}")
        log_info(f"[resolver] репозиторий {repo} успешно клонирован в {cache_path}")
    elif not offline:
        log_info(f"[resolver] обновляю кеш репозитория {repo} в {cache_path}")
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
        log_info(f"[resolver] создаю рабочую копию из {cache_repo} в {target_repo}")
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
        log_info(f"[resolver] commit {commit} найден в кеше {cache_repo}")

    # Обновить локальную копию из кеша (без обращения в сеть)
    if commit:
        log_info(f"[resolver] синхронизирую {target_repo} с кешем {cache_repo} и переключаюсь на {commit}")
        run_command(["git", "-C", str(target_repo), "remote", "set-url", "origin", str(cache_repo)])
        run_command(["git", "-C", str(target_repo), "fetch", "origin", "--tags", "-q"])

    checkout_target = commit or "HEAD"
    log_info(f"[resolver] checkout --force {checkout_target} в {target_repo}")
    code, out, err = run_command(["git", "-C", str(target_repo), "checkout", "--force", checkout_target])
    if code != 0:
        raise RuntimeError(f"Не удалось переключиться на {checkout_target} в {target_repo}: {err or out}")
    run_command(["git", "-C", str(target_repo), "reset", "--hard", checkout_target])
    run_command(["git", "-C", str(target_repo), "clean", "-fdx"])
    log_info(f"[resolver] рабочая копия {target_repo} готова к использованию")


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


def _install_custom_node_dependencies(
    *,
    python_exe: str,
    comfy_home: pathlib.Path,
    wheels_dir: Optional[pathlib.Path],
    offline: bool,
) -> None:
    if offline:
        return

    custom_nodes_dir = comfy_home / "custom_nodes"
    try:
        entries = sorted(custom_nodes_dir.iterdir())
    except FileNotFoundError:
        return
    except OSError as exc:
        log_warn(f"Не удалось прочитать custom_nodes: {exc}")
        return

    processed: Set[pathlib.Path] = set()

    for node_dir in entries:
        try:
            if not node_dir.is_dir():
                continue
        except OSError:
            continue

        requirements_path = node_dir / "requirements.txt"

        if not requirements_path.exists():
            continue

        try:
            install_key = requirements_path.resolve()
        except OSError:
            install_key = requirements_path

        if install_key in processed:
            continue
        processed.add(install_key)

        cmd = [python_exe, "-m", "pip", "install", "-r", str(requirements_path)]
        if wheels_dir:
            cmd.extend(["--no-index", "--find-links", str(wheels_dir)])

        code, out, err = run_command(cmd)
        if code != 0:
            node_name = node_dir.name
            log_warn(
                f"pip install для custom-ноды {node_name} завершился с кодом {code}: {err or out}"
            )


def _parse_requirement_name(raw_line: str) -> Optional[str]:
    line = raw_line.split("#", 1)[0].strip()
    if not line or line.startswith(("-", "#")):
        return None

    if line.startswith(("http://", "https://", "git+", "file:", "svn+", "hg+", "bzr+", "ssh:")):
        return None

    if ";" in line:
        line = line.split(";", 1)[0].strip()

    for separator in ("==", "~=", ">=", "<=", "!=", ">", "<", "="):
        if separator in line:
            line = line.split(separator, 1)[0].strip()
            break

    if "[" in line:
        line = line.split("[", 1)[0].strip()

    normalized = line.replace("-", "_")
    if normalized:
        return normalized
    return None


def _collect_custom_node_requirements(comfy_home: pathlib.Path) -> Dict[str, List[str]]:
    requirements: Dict[str, List[str]] = {}
    custom_nodes_dir = comfy_home / "custom_nodes"

    try:
        entries = sorted(custom_nodes_dir.iterdir())
    except FileNotFoundError:
        return requirements
    except OSError as exc:
        log_warn(f"Не удалось прочитать custom_nodes: {exc}")
        return requirements

    for node_dir in entries:
        try:
            if not node_dir.is_dir():
                continue
        except OSError:
            continue

        req_file = node_dir / "requirements.txt"
        if not req_file.exists():
            continue

        try:
            lines = req_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            log_warn(f"Не удалось прочитать {req_file}: {exc}")
            continue

        parsed: List[str] = []
        for raw in lines:
            name = _parse_requirement_name(raw)
            if name:
                parsed.append(name)

        if parsed:
            requirements[node_dir.name] = parsed

    return requirements


def _verify_custom_node_requirements(
    *,
    python_exe: Optional[str],
    comfy_home: pathlib.Path,
    verbose: bool,
) -> None:
    if not python_exe:
        python_exe = _select_python_executable()

    mapping = _collect_custom_node_requirements(comfy_home)
    if not mapping:
        if verbose:
            log_info("[resolver] requirements.txt для кастом-нод не найдены — проверка пропущена")
        return

    all_packages: List[str] = []
    for names in mapping.values():
        all_packages.extend(names)

    if not all_packages:
        if verbose:
            log_info("[resolver] кастом-ноды не содержат зависимостей для проверки")
        return

    unique_packages = sorted({name for name in all_packages})

    script = (
        "import json, sys\n"
        "from importlib import metadata\n"
        "packages = json.loads(sys.argv[1])\n"
        "missing = []\n"
        "for pkg in packages:\n"
        "    try:\n"
        "        metadata.distribution(pkg)\n"
        "    except metadata.PackageNotFoundError:\n"
        "        missing.append(pkg)\n"
        "print(json.dumps(missing))\n"
    )

    code, out, err = run_command([python_exe, "-c", script, json.dumps(unique_packages)])
    if code != 0:
        log_warn(f"Не удалось проверить зависимости кастом-нод (python={python_exe}): {err or out}")
        return

    try:
        missing_list = json.loads(out.strip() or "[]")
    except json.JSONDecodeError as exc:
        log_warn(f"Ошибка парсинга результатов проверки зависимостей: {exc}; вывод={out}")
        return

    missing_set = {str(item) for item in missing_list if item}
    if not missing_set:
        if verbose:
            log_info("[resolver] зависимости кастом-нод установлены")
        return

    affected: Dict[str, List[str]] = {}
    for node_name, names in mapping.items():
        missing_for_node = [name for name in names if name in missing_set]
        if missing_for_node:
            affected[node_name] = missing_for_node

    for node_name, names in affected.items():
        log_warn(
            f"Недостающие зависимости для кастом-ноды {node_name}: {', '.join(sorted(set(names)))}"
        )

    # Попытка установить недостающие пакеты напрямую
    log_info(f"[resolver] попытка установить недостающие зависимости: {', '.join(sorted(missing_set))}")
    cmd = [python_exe, "-m", "pip", "install"] + sorted(missing_set)
    code, out, err = run_command(cmd)
    
    if code != 0:
        log_warn(f"pip install недостающих зависимостей завершился с кодом {code}: {err or out}")
    
    # Повторная проверка после попытки установки
    code, out, err = run_command([python_exe, "-c", script, json.dumps(unique_packages)])
    if code != 0:
        log_warn(f"Не удалось повторно проверить зависимости после установки: {err or out}")
        raise RuntimeError(
            "Не установлены Python-зависимости для кастом-нод: "
            + ", ".join(sorted(missing_set))
        )
    
    try:
        still_missing = json.loads(out.strip() or "[]")
    except json.JSONDecodeError as exc:
        log_warn(f"Ошибка парсинга результатов повторной проверки: {exc}; вывод={out}")
        raise RuntimeError(
            "Не установлены Python-зависимости для кастом-нод: "
            + ", ".join(sorted(missing_set))
        )
    
    still_missing_set = {str(item) for item in still_missing if item}
    if still_missing_set:
        log_error(
            "После попытки установки все еще недостают зависимости: "
            + ", ".join(sorted(still_missing_set))
        )
        raise RuntimeError(
            "Не установлены Python-зависимости для кастом-нод: "
            + ", ".join(sorted(still_missing_set))
        )
    
    log_info("[resolver] недостающие зависимости успешно установлены")


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
    log_info(f"[resolver] подготовка окружения для версии {version_id}")
    comfy_home = target_path or _pick_default_comfy_home(version_id)
    comfy_home = comfy_home.resolve()
    models_dir = (models_dir_override or _models_dir_default(comfy_home)).resolve()

    # Ensure base dirs
    comfy_home.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    log_info(f"[resolver] пути: COMFY_HOME={comfy_home}, MODELS_DIR={models_dir}")
 
    ready_python = _venv_python_path(comfy_home / ".venv")
    has_python = ready_python.exists() and os.access(str(ready_python), os.X_OK)
    has_comfy_checkout = (comfy_home / "main.py").exists()

    if has_python and has_comfy_checkout:
        log_info("[resolver] обнаружен готовый build, пропускаю подготовку и установки")
        os.environ["COMFY_HOME"] = str(comfy_home)
        os.environ["MODELS_DIR"] = str(models_dir)
        _write_extra_model_paths(
            comfy_home=comfy_home,
            models_dir=models_dir,
            resolved_models=resolved.get("models"),
        )
        log_info("[resolver] окружение ComfyUI готово (использую существующий build)")
        return comfy_home, models_dir

    # Clone or update ComfyUI
    comfy = resolved.get("comfy") or {}
    repo = comfy.get("repo") if isinstance(comfy, dict) else None
    commit = comfy.get("commit") if isinstance(comfy, dict) else None
    if not isinstance(repo, str) or not repo:
        raise RuntimeError("Resolved comfy.repo is required")
    repo_dir = comfy_home
 
    lock_path = resolved_cache_dir() / f"{version_id}.lock.json"
    lock = load_lock(str(lock_path)) if lock_path.exists() else {}

    locked_interpreter = _select_python_from_lock(lock)

    signature = _signature_from_resolved(resolved)
    marker = _load_prepared_marker(comfy_home)

    venv_python_path = _venv_python_path(comfy_home / ".venv")
    locked_interpreter_path = pathlib.Path(locked_interpreter) if locked_interpreter else None

    should_prepare = marker != signature
    if not should_prepare and not locked_interpreter_path:
        if not venv_python_path.exists():
            log_warn(
                f"[resolver] маркер найден, но виртуальное окружение отсутствует ({venv_python_path}); переинициализирую"
            )
            should_prepare = True
            marker = None

    if not should_prepare:
        log_info("[resolver] найден маркер подготовленного окружения, пропускаю повторную установку")

    if should_prepare:
        log_info(f"[resolver] готовлю ComfyUI из {repo} (commit={commit})")
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

    python_path = _venv_python_from_env()
    if python_path:
        ensure_venv = python_path
    else:
        ensure_venv = _ensure_comfy_venv(comfy_home, verbose=False)
        python_path = ensure_venv or locked_interpreter or _select_python_executable()

    # Ensure custom_nodes directory exists in checkout (may be absent in repo for fresh clone)
    (repo_dir / "custom_nodes").mkdir(parents=True, exist_ok=True)
    if should_prepare:
        log_info(f"[resolver] директория custom_nodes готова")

    log_info(f"[resolver] выбран интерпретатор Python: {python_path}")
    req = repo_dir / "requirements.txt"
    if should_prepare and req.exists() and not offline:
        log_info(f"[resolver] устанавливаю зависимости из {req}")
        cmd = [python_path, "-m", "pip", "install"]
        if wheels_dir:
            cmd.extend(["--no-index", "--find-links", str(wheels_dir)])
        cmd.extend(["-r", str(req)])
        code, out, err = run_command(cmd)
        if code != 0:
            log_warn(f"pip install ComfyUI requirements failed: {err or out}")
        else:
            log_info("[resolver] зависимости ComfyUI установлены")

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
            if should_prepare:
                if not (cache_path / ".git").exists():
                    if offline:
                        log_warn(
                            f"Offline режим: кэш для ноды {n_repo} не найден ({cache_path}), пропускаем"
                        )
                        continue
                    log_info(f"[resolver] клонирую кастом-ноду {n_repo} -> {cache_path}")
                    code, out, err = run_command(["git", "clone", n_repo, str(cache_path)])
                    if code != 0:
                        log_warn(f"Failed to clone node {n_name}: {err or out}")
                        continue
                if n_commit:
                    if not offline:
                        run_command(["git", "-C", str(cache_path), "fetch", "--all", "--tags", "-q"])  # best-effort
                    run_command(["git", "-C", str(cache_path), "checkout", n_commit])
                log_info(f"[resolver] кастом-нода {n_name} готова")
            dst = repo_dir / "custom_nodes" / n_name
            _ensure_symlink(cache_path, dst)

    if should_prepare:
        _install_custom_node_dependencies(
            python_exe=python_path,
            comfy_home=comfy_home,
            wheels_dir=wheels_dir,
            offline=offline,
        )

        log_info("[resolver] подготовка моделей")
        _prepare_models(
            resolved_models=resolved.get("models") or [],
            models_dir=models_dir,
            comfy_home=comfy_home,
            offline=offline,
        )

        _save_prepared_marker(comfy_home, signature)
        log_info("[resolver] окружение ComfyUI подготовлено и промаркеровано")
    else:
        log_info("[resolver] пропускаю подготовку, окружение уже готово")

    # Export env
    os.environ["COMFY_HOME"] = str(comfy_home)
    os.environ["MODELS_DIR"] = str(models_dir)
    _write_extra_model_paths(
        comfy_home=comfy_home,
        models_dir=models_dir,
        resolved_models=resolved.get("models"),
    )

    try:
        _verify_custom_node_requirements(
            python_exe=python_path,
            comfy_home=comfy_home,
            verbose=should_prepare,
        )
    except RuntimeError as exc:
        raise RuntimeError(str(exc))

    log_info("[resolver] окружение ComfyUI готово")
    return comfy_home, models_dir


def _prepare_models(
    *,
    resolved_models: List[Dict[str, object]],
    models_dir: pathlib.Path,
    comfy_home: pathlib.Path,
    offline: bool,
) -> None:
    if not isinstance(resolved_models, list) or not resolved_models:
        return

    offline_effective = bool(offline or verify_models.is_offline_mode())
    env_vars = {
        "MODELS_DIR": str(models_dir),
        "COMFY_HOME": str(comfy_home),
    }

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

        target_expanded = expand_env(target_path_raw, extra_env=env_vars).strip()
        if not target_expanded:
            log_warn(f"models entry '{name}' пропущен: target_path пуст после развёртки")
            continue

        target_path = pathlib.Path(target_expanded)
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

        if not target_abs.exists():
            existing_path = _find_existing_model(
                models_dir=models_dir,
                target_abs=target_abs,
                checksum_algo=checksum_algo,
                checksum_hex=checksum_hex,
            )
            if existing_path:
                try:
                    if existing_path.resolve() == target_abs:
                        log_info(f"Модель '{name}' уже присутствует: {target_abs}")
                        continue
                except Exception:
                    pass

                try:
                    log_info(
                        f"Модель '{name}' найдена в кеше: {existing_path}, создаю симлинк -> {target_abs}"
                    )
                    target_abs.parent.mkdir(parents=True, exist_ok=True)
                    if target_abs.is_symlink():
                        target_abs.unlink()
                    os.symlink(existing_path, target_abs)
                    log_info(f"Модель '{name}' подключена симлинком из {existing_path}")
                    continue
                except OSError as exc:
                    raise RuntimeError(
                        f"Не удалось создать симлинк для модели '{name}' из {existing_path}: {exc}"
                    )
                except Exception as exc:
                    log_warn(f"Не удалось создать симлинк для модели '{name}' из {existing_path}: {exc}")

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

        if not source:
            log_warn(f"Модель '{name}' отсутствует по пути {target_abs} и не имеет source для загрузки")
            continue

        try:
            with tempfile.TemporaryDirectory(prefix="model_fetch_", dir=str(models_dir)) as tmp_dir:
                log_info(f"Загрузка модели '{name}' из source: {source}")
                tmp_path = verify_models.fetch_to_temp(source, tmp_dir=tmp_dir, timeout=_MODEL_FETCH_TIMEOUT)
                if checksum_hex and checksum_algo:
                    actual = verify_models.compute_checksum(tmp_path, algo=checksum_algo).split(":", 1)[1]
                    if actual != checksum_hex:
                        raise RuntimeError("downloaded checksum mismatch")
                verify_models.atomic_copy(tmp_path, str(target_abs))
                log_info(f"Модель '{name}' сохранена: {target_abs}")
        except Exception as exc:
            raise RuntimeError(
                f"Не удалось загрузить модель '{name}' (source={source}, target={target_abs}): {exc}"
            ) from exc


def _write_extra_model_paths(
    *,
    comfy_home: pathlib.Path,
    models_dir: pathlib.Path,
    resolved_models: Optional[List[Dict[str, object]]],
) -> None:
    extra_yaml = comfy_home / "extra_model_paths.yaml"
    mapping = {
        "base_path": str(models_dir),
    }

    default_subdirs = [
        "audio_encoders",
        "checkpoints",
        "clip",
        "clip_vision",
        "configs",
        "controlnet",
        "diffusion_models",
        "embeddings",
        "inpaint",
        "loras",
        "photomaker",
        "text_encoders",
        "unet",
        "upscale_models",
        "vae",
    ]

    for subdir in default_subdirs:
        mapping[subdir] = str(models_dir / subdir)

    if resolved_models:
        for model in resolved_models:
            if not isinstance(model, dict):
                continue
            target_path_raw = str(model.get("target_path") or "").strip()
            if not target_path_raw:
                continue
            target_path = pathlib.Path(target_path_raw)
            relative_root: Optional[pathlib.Path]
            if target_path.is_absolute():
                try:
                    relative_root = target_path.relative_to(models_dir)
                except ValueError:
                    relative_root = None
            else:
                relative_root = target_path

            if relative_root is None:
                continue

            parts = list(relative_root.parts)
            current = pathlib.Path()
            for part in parts[:-1]:
                current = current / part
                key = str(current)
                if key:
                    mapping.setdefault(key, str(models_dir / current))

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
        raise SpecValidationError(f"{source_path}: поле 'comfy.repo' обязателен и должно быть строкой")
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
        target_path_value = _optional_trimmed_str(
            entry.get("target_path"), source_path, f"models[{idx}].target_path"
        )
        path_value = _optional_trimmed_str(entry.get("path"), source_path, f"models[{idx}].path")

        model_entry: Dict[str, Optional[str]] = {
            "source": source_value.strip(),
            "name": name_value,
            "target_subdir": target_subdir_value,
            "target_path": target_path_value,
        }

        if path_value is not None:
            model_entry["path"] = path_value

        models.append(model_entry)

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


def _ensure_comfy_venv(
    comfy_home: pathlib.Path,
    *,
    verbose: bool = False,
) -> Optional[str]:
    """Гарантирует наличие venv внутри COMFY_HOME и возвращает путь к python."""

    try:
        comfy_home.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log_warn(f"Не удалось создать COMFY_HOME {comfy_home}: {exc}")
        return None

    if not os.access(str(comfy_home), os.W_OK | os.X_OK):
        if verbose:
            log_warn(f"Нет доступа на запись в {comfy_home}, пропускаю создание venv")
        return None

    venv_dir = comfy_home / ".venv"
    python_path = _venv_python_path(venv_dir)

    if python_path.exists() and os.access(str(python_path), os.X_OK):
        return str(python_path)

    base_python = _select_python_executable()
    venv_mode = os.environ.get("COMFY_VENV_MODE", "copies").strip().lower()

    venv_args = [base_python, "-m", "venv"]
    if venv_mode in {"copies", "copy"}:
        venv_args.append("--copies")
        if verbose:
            log_info(f"Создаю venv (copies): {venv_dir} (python={base_python})")
    elif venv_mode in {"symlinks", "link", "links"}:
        venv_args.append("--symlinks")
        if verbose:
            log_info(f"Создаю venv (symlinks): {venv_dir} (python={base_python})")
    else:
        if verbose:
            log_info(f"Создаю venv (default): {venv_dir} (python={base_python})")

    try:
        code, out, err = run_command(venv_args + [str(venv_dir)])
    except Exception as exc:
        log_warn(f"Исключение при создании venv в {venv_dir}: {exc}")
        return None

    if code != 0 or not python_path.exists():
        log_warn(f"Не удалось создать venv в {venv_dir}: {err or out}")
        return None

    if verbose:
        log_info(f"Venv готов: {python_path}")
    return str(python_path)


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
        ensured_python = _ensure_comfy_venv(pathlib.Path(comfy_home), verbose=verbose)
        if ensured_python:
            return ensured_python

    # 3) Системный python
    sys_py = _select_python_executable()
    if verbose:
        log_info(f"Using system Python interpreter: {sys_py}")
    return sys_py


def _select_python_from_lock(lock: Dict[str, object]) -> Optional[str]:
    if not isinstance(lock, dict):
        return None
    python = lock.get("python")
    if not isinstance(python, dict):
        return None
    interpreter = python.get("interpreter")
    if not isinstance(interpreter, str) or not interpreter:
        return None
    path = pathlib.Path(interpreter)
    if path.exists() and os.access(str(path), os.X_OK):
        return str(path)
    return None


def _find_existing_model(
    *,
    models_dir: pathlib.Path,
    target_abs: pathlib.Path,
    checksum_algo: Optional[str],
    checksum_hex: Optional[str],
    search_depth_limit: int = 1000,
) -> Optional[pathlib.Path]:
    """Ищет модель в models_dir и в стандартных путях volume."""
    name = target_abs.name
    
    # Список директорий для поиска
    search_dirs = [models_dir]
    
    # Добавляем стандартные пути volume (если они отличаются от models_dir)
    standard_paths = [
        pathlib.Path("/runpod-volume/models"),
        pathlib.Path("/runpod-volume/models"),
    ]
    for std_path in standard_paths:
        if std_path.exists() and std_path.resolve() != models_dir.resolve():
            search_dirs.append(std_path)
    
    candidates = []
    for search_dir in search_dirs:
        try:
            for idx, candidate in enumerate(search_dir.rglob(name)):
                if idx > search_depth_limit:
                    log_warn(
                        f"Поиск модели '{name}' в {search_dir} достиг лимита {search_depth_limit}; остановка"
                    )
                    break
                candidates.append(candidate)
        except Exception as exc:
            log_warn(f"Не удалось обойти {search_dir} при поиске модели {name}: {exc}")
            continue

    for candidate in candidates:
        try:
            if candidate.resolve() == target_abs.resolve():
                continue
        except Exception:
            continue

        if not candidate.is_file():
            continue

        if checksum_algo and checksum_hex:
            try:
                actual = verify_models.compute_checksum(str(candidate), algo=checksum_algo).split(":", 1)[1]
            except Exception as exc:
                log_warn(f"Не удалось вычислить checksum для кандидата {candidate}: {exc}")
                continue
            if actual != checksum_hex:
                continue

        return candidate

    return None


PREPARED_MARKER_FILENAME = ".runpod_prepared.json"


def _prepared_marker_path(comfy_home: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(comfy_home) / PREPARED_MARKER_FILENAME


def _load_prepared_marker(comfy_home: pathlib.Path) -> Optional[Dict[str, object]]:
    path = _prepared_marker_path(comfy_home)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log_warn(f"Не удалось прочитать маркер подготовленного окружения {path}: {exc}")
        return None


def _save_prepared_marker(comfy_home: pathlib.Path, signature: Dict[str, object]) -> None:
    path = _prepared_marker_path(comfy_home)
    try:
        path.write_text(json.dumps(signature, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        log_warn(f"Не удалось записать маркер подготовленного окружения {path}: {exc}")


def _signature_from_resolved(resolved: Dict[str, object]) -> Dict[str, object]:
    comfy = resolved.get("comfy") if isinstance(resolved, dict) else {}
    comfy_repo = ""
    comfy_commit = ""
    if isinstance(comfy, dict):
        comfy_repo = str(comfy.get("repo") or "")
        comfy_commit = str(comfy.get("commit") or "")

    custom_nodes_raw = resolved.get("custom_nodes") if isinstance(resolved, dict) else []
    custom_nodes: List[Dict[str, str]] = []
    if isinstance(custom_nodes_raw, list):
        for entry in custom_nodes_raw:
            if not isinstance(entry, dict):
                continue
            custom_nodes.append(
                {
                    "repo": str(entry.get("repo") or ""),
                    "commit": str(entry.get("commit") or ""),
                }
            )
    custom_nodes.sort(key=lambda x: (x.get("repo", ""), x.get("commit", "")))

    return {
        "version_id": str(resolved.get("version_id") or ""),
        "comfy": {"repo": comfy_repo, "commit": comfy_commit},
        "custom_nodes": custom_nodes,
    }



