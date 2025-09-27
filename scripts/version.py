#!/usr/bin/env python3
"""Unified CLI for schema v2 version workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rp_handler import main as handler_main
from rp_handler.main import spec_path_for_version
from rp_handler.cache import resolved_cache_dir
from rp_handler.resolver import (
    SpecValidationError,
    resolve_version_spec,
    save_resolved_lock,
    realize_from_resolved,
    _pick_default_comfy_home,
    _models_dir_default,
    _venv_python_from_env,
    _select_python_executable,
)


def _log_info(message: str) -> None:
    print(f"[INFO] {message}")


def _log_warn(message: str) -> None:
    print(f"[WARN] {message}")


def _log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def _looks_like_commit(value: Optional[str]) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    return len(value) == 40 and all(ch in "0123456789abcdef" for ch in value.lower())


def _slug_from_repo(repo_url: str) -> str:
    tail = repo_url.rstrip("/").split("/")[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail or "repo"


def _split_repo_ref(raw: str) -> Tuple[str, Optional[str]]:
    value = raw.strip()
    if not value:
        raise ValueError("Пустое значение репозитория")

    if value.startswith("git@") and value.count("@") == 1:
        return value, None

    idx = value.rfind("@")
    if idx == -1:
        return value, None

    if "://" in value:
        scheme_idx = value.index("://")
        if idx < scheme_idx + 3:
            # '@' относится к схеме (например, https://user@host)
            return value, None

    repo = value[:idx]
    ref = value[idx + 1 :]
    if not ref:
        return repo, None
    return repo, ref


def _git_resolve_commit(repo: str, ref: Optional[str]) -> str:
    if _looks_like_commit(ref):
        return str(ref)

    ref_to_use = ref or "HEAD"
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo, ref_to_use],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - extremely unlikely in CI
        raise RuntimeError("git не найден в PATH") from exc

    if result.returncode != 0:
        raise RuntimeError(f"git ls-remote завершился с кодом {result.returncode}: {result.stderr.strip()}")

    stdout = result.stdout.strip().splitlines()
    for line in stdout:
        parts = line.split("\t", 1)
        if parts and _looks_like_commit(parts[0]):
            return parts[0]

    raise RuntimeError(f"Не удалось получить commit для {repo} {ref_to_use}")


def _load_jsonish(value: str) -> Optional[Any]:
    text = value.strip()
    if not text:
        return None
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)

    path = pathlib.Path(value)
    if path.exists():
        data = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(data)
        return json.loads(data)

    return None


def _parse_nodes(values: List[str], file_path: Optional[str]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    if file_path:
        loaded = _load_jsonish(file_path)
        if isinstance(loaded, list):
            for item in loaded:
                if not isinstance(item, dict):
                    raise ValueError("Файл кастом-нод должен содержать объекты JSON")
                result.append(item)
        elif isinstance(loaded, dict):
            result.append(loaded)
        elif loaded is not None:
            raise ValueError("Не удалось распарсить файл кастом-нод")
    for value in values or []:
        loaded = _load_jsonish(value)
        if isinstance(loaded, list):
            for item in loaded:
                if not isinstance(item, dict):
                    raise ValueError("Список кастом-нод должен содержать объекты JSON")
                result.append(item)
            continue
        if isinstance(loaded, dict):
            result.append(loaded)
            continue

        repo, ref = _split_repo_ref(value)
        node: Dict[str, Any] = {"repo": repo}
        if ref:
            node["ref"] = ref
        result.append(node)
    return result


def _parse_models(values: List[str], file_path: Optional[str]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    if file_path:
        loaded = _load_jsonish(file_path)
        if isinstance(loaded, list):
            for item in loaded:
                if not isinstance(item, dict):
                    raise ValueError("Файл моделей должен содержать объекты JSON")
                result.append(item)
        elif isinstance(loaded, dict):
            result.append(loaded)
        elif loaded is not None:
            raise ValueError("Не удалось распарсить файл моделей")
    for value in values or []:
        loaded = _load_jsonish(value)
        if isinstance(loaded, list):
            for item in loaded:
                if not isinstance(item, dict):
                    raise ValueError("Список моделей должен содержать объекты JSON")
                result.append(item)
            continue
        if isinstance(loaded, dict):
            result.append(loaded)
            continue
        raise ValueError("Модели необходимо указывать JSON-объектом или файлом")
    return result


def _compute_checksum(path: pathlib.Path, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return f"{algo}:{h.hexdigest()}"


def _default_model_name(source: str) -> str:
    parsed = urllib.parse.urlparse(source)
    candidate = pathlib.Path(parsed.path or "model").name
    return candidate or "model"


def _resolve_models(
    models: List[Dict[str, Any]],
    *,
    models_root: Optional[pathlib.Path],
    auto_checksum: bool,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("Элемент models должен быть объектом JSON")
        if "source" not in model or not str(model["source"]).strip():
            raise ValueError("Каждый элемент models должен содержать поле 'source'")

        source = str(model["source"]).strip()
        name = str(model.get("name") or _default_model_name(source))
        target_subdir = model.get("target_subdir")
        if isinstance(target_subdir, str) and target_subdir.strip():
            target_subdir = target_subdir.strip()
        else:
            target_subdir = None

        target_path = model.get("target_path") or model.get("path")
        if isinstance(target_path, str) and target_path.strip():
            target_path_str = target_path.strip()
        else:
            rel = pathlib.Path(name)
            if target_subdir:
                rel = pathlib.Path(target_subdir) / rel
            target_path_str = str(rel)

        checksum = model.get("checksum")
        if auto_checksum and not checksum and models_root is not None:
            candidate_path = pathlib.Path(target_path_str)
            if not candidate_path.is_absolute():
                candidate_path = models_root / candidate_path
            if candidate_path.exists() and candidate_path.is_file():
                try:
                    checksum = _compute_checksum(candidate_path)
                except OSError as exc:
                    _log_warn(f"Не удалось вычислить checksum для {candidate_path}: {exc}")
            else:
                _log_warn(f"Файл модели не найден локально: {candidate_path}")

        entry: Dict[str, Any] = {
            "source": source,
            "name": name,
            "target_subdir": target_subdir,
            "target_path": target_path_str,
        }
        if checksum:
            entry["checksum"] = checksum
        normalized.append(entry)
    return normalized


def _prepare_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    prepared: List[Dict[str, Any]] = []
    for node in nodes:
        if "repo" not in node or not str(node["repo"]).strip():
            raise ValueError("Каждый элемент custom_nodes должен содержать поле 'repo'")
        repo_raw = str(node["repo"]).strip()
        repo, ref_from_value = _split_repo_ref(repo_raw)
        ref = node.get("ref") or ref_from_value
        commit = node.get("commit")
        if not commit:
            commit = _git_resolve_commit(repo, ref)
        name = node.get("name") or _slug_from_repo(repo)
        prepared.append({
            "name": str(name),
            "repo": repo,
            "ref": ref,
            "commit": commit,
        })
    return prepared


def _guess_models_root(arg_value: Optional[str]) -> Optional[pathlib.Path]:
    if arg_value:
        return pathlib.Path(arg_value).expanduser().resolve()
    env_value = os.environ.get("MODELS_DIR")
    if env_value:
        return pathlib.Path(env_value).expanduser().resolve()
    comfy_home = os.environ.get("COMFY_HOME")
    if comfy_home:
        return pathlib.Path(comfy_home).expanduser().resolve() / "models"
    return None


def _prepare_resolved(spec_path: pathlib.Path, offline_flag: bool) -> tuple[dict, bool]:
    resolved = resolve_version_spec(spec_path, offline=offline_flag)
    options = resolved.get("options") or {}
    offline_effective = bool(options.get("offline") or offline_flag)
    skip_models_effective = bool(options.get("skip_models"))
    resolved["options"] = {
        **options,
        "offline": offline_effective,
        "skip_models": skip_models_effective,
    }
    return resolved, offline_effective


def _format_plan(resolved: dict, target_path: pathlib.Path, models_dir: Optional[pathlib.Path], offline: bool, wheels_dir: Optional[pathlib.Path]) -> list[str]:
    lines = [
        f"  version_id:  {resolved.get('version_id')}",
        f"  target:      {target_path}",
        f"  offline:     {offline}",
    ]
    comfy = resolved.get("comfy") if isinstance(resolved, dict) else None
    if isinstance(comfy, dict):
        lines.append(f"  comfy.repo:  {comfy.get('repo')}")
        lines.append(f"  comfy.ref:   {comfy.get('ref')}")
        lines.append(f"  comfy.commit:{comfy.get('commit')}")
    if models_dir:
        lines.append(f"  models_dir:  {models_dir}")
    if wheels_dir:
        lines.append(f"  wheels_dir:  {wheels_dir}")
    custom_nodes = resolved.get("custom_nodes")
    if isinstance(custom_nodes, list) and custom_nodes:
        lines.append("  custom_nodes:")
        for node in custom_nodes:
            if isinstance(node, dict):
                name = node.get("name") or node.get("repo")
                lines.append(f"    - {name} (commit: {node.get('commit')})")
    models = resolved.get("models")
    if isinstance(models, list) and models:
        lines.append("  models:")
        for model in models:
            if isinstance(model, dict):
                name = model.get("name") or model.get("source")
                target = model.get("target_subdir") or model.get("target_path") or "-"
                lines.append(f"    - {name} -> {target}")
    return lines


def _resolve_spec_path(version_id: str) -> pathlib.Path:
    spec_path = spec_path_for_version(version_id)
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec file not found for version '{version_id}': {spec_path}")
    return spec_path


def _lock_path_for_version(version_id: str) -> pathlib.Path:
    return resolved_cache_dir() / f"{version_id}.lock.json"


def _update_runtime_env(comfy_home: pathlib.Path, models_dir: pathlib.Path) -> None:
    os.environ["COMFY_HOME"] = str(comfy_home)
    os.environ["MODELS_DIR"] = str(models_dir)


def cmd_create(args: argparse.Namespace) -> int:
    repo, ref = _split_repo_ref(args.repo)
    try:
        commit = _git_resolve_commit(repo, ref)
    except RuntimeError as exc:
        _log_error(f"Не удалось определить commit для {repo}: {exc}")
        return 2

    models_root = _guess_models_root(args.models_root)
    try:
        nodes = _prepare_nodes(_parse_nodes(args.nodes, args.nodes_file))
        models = _resolve_models(
            _parse_models(args.models, args.models_file),
            models_root=models_root,
            auto_checksum=args.auto_checksum,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        _log_error(f"Ошибка обработки входных данных: {exc}")
        return 2

    spec: Dict[str, Any] = {
        "schema_version": 2,
        "version_id": args.version_id,
        "comfy": {
            "repo": repo,
            "commit": commit,
        },
        "custom_nodes": nodes,
        "models": models,
        "env": {},
        "options": {},
    }
    if ref:
        spec["comfy"]["ref"] = ref

    output_path = pathlib.Path(args.output) if args.output else (pathlib.Path("versions") / f"{args.version_id}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    _log_info(f"Спецификация сохранена: {output_path}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    try:
        spec_path = _resolve_spec_path(args.version_id)
        resolved, offline_effective = _prepare_resolved(spec_path, args.offline)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except SpecValidationError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 2

    lock_path = save_resolved_lock(resolved)
    print("[OK] Resolved spec")
    print(f"  version_id: {resolved.get('version_id')}")
    print(f"  offline:    {offline_effective}")
    print(f"  saved_to:   {lock_path}")
    return 0


def cmd_realize(args: argparse.Namespace) -> int:
    try:
        spec_path = _resolve_spec_path(args.version_id)
        resolved, offline_effective = _prepare_resolved(spec_path, args.offline)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except SpecValidationError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 2

    version_id = str(resolved.get("version_id") or "version")
    target_path = pathlib.Path(args.target).resolve() if args.target else _pick_default_comfy_home(version_id)
    models_override = pathlib.Path(args.models_dir).resolve() if args.models_dir else None
    wheels_dir = pathlib.Path(args.wheels_dir).resolve() if args.wheels_dir else None

    print("[INFO] План развёртки:")
    for line in _format_plan(resolved, target_path, models_override, offline_effective, wheels_dir):
        print(line)

    if args.dry_run:
        print("[DRY-RUN] Завершено без изменений")
        return 0

    lock_path = save_resolved_lock(resolved)
    comfy_home, models_dir = realize_from_resolved(
        resolved,
        target_path=target_path,
        models_dir_override=models_override,
        wheels_dir=wheels_dir,
        offline=offline_effective,
    )

    print("[OK] Версия готова")
    print(f"  resolved_lock: {lock_path}")
    print(f"  COMFY_HOME:    {comfy_home}")
    print(f"  MODELS_DIR:   {models_dir}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        spec_path = _resolve_spec_path(args.version_id)
        resolved, offline_effective = _prepare_resolved(spec_path, args.offline)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except SpecValidationError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 2

    lock_path = save_resolved_lock(resolved)

    target = _pick_default_comfy_home(args.version_id)
    plan_lines = _format_plan(resolved, target, None, offline_effective, None)
    print("[OK] Spec resolved successfully")
    for line in plan_lines:
        print(line)
    print(f"  resolved_lock: {lock_path}")
    return 0


def cmd_run_ui(args: argparse.Namespace) -> int:
    try:
        spec_path = _resolve_spec_path(args.version_id)
        resolved, offline_effective = _prepare_resolved(spec_path, args.offline)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except SpecValidationError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 2

    target_path = pathlib.Path(args.target).resolve() if args.target else _pick_default_comfy_home(args.version_id)
    models_override = pathlib.Path(args.models_dir).resolve() if args.models_dir else None
    wheels_dir = pathlib.Path(args.wheels_dir).resolve() if args.wheels_dir else None

    print("[INFO] Подготовка окружения для UI:")
    for line in _format_plan(resolved, target_path, models_override, offline_effective, wheels_dir):
        print(line)

    lock_path = save_resolved_lock(resolved)
    comfy_home, models_dir = realize_from_resolved(
        resolved,
        target_path=target_path,
        models_dir_override=models_override,
        wheels_dir=wheels_dir,
        offline=offline_effective,
    )

    effective_models_dir = models_override or models_dir
    _update_runtime_env(comfy_home, effective_models_dir)

    python_exe = _venv_python_from_env() or _select_python_executable()
    main_py = comfy_home / "main.py"
    if not main_py.exists():
        print(f"[ERROR] Не найден ComfyUI main.py: {main_py}")
        return 2

    cmd = [python_exe, str(main_py), "--listen", args.host, "--port", str(args.port)]
    extra_args = list(args.extra_args or [])
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]
    cmd.extend(extra_args)

    print("[INFO] Запуск ComfyUI:")
    print("  " + " ".join(cmd))
    print(f"  COMFY_HOME={comfy_home}")
    print(f"  MODELS_DIR={effective_models_dir}")
    print(f"  resolved_lock={lock_path}")

    try:
        return subprocess.call(cmd, env=os.environ.copy())
    except KeyboardInterrupt:
        print("[INFO] Остановка по Ctrl+C")
        return 0


def cmd_run_handler(args: argparse.Namespace) -> int:
    if args.offline:
        prev_offline = os.environ.get("COMFY_OFFLINE")
        os.environ["COMFY_OFFLINE"] = "1"
    else:
        prev_offline = None

    cli_args = [
        "--version-id",
        args.version_id,
        "--workflow",
        args.workflow,
        "--output",
        args.output,
    ]
    if args.out_file:
        cli_args.extend(["--out-file", args.out_file])
    if args.gcs_bucket:
        cli_args.extend(["--gcs-bucket", args.gcs_bucket])
    if args.gcs_prefix:
        cli_args.extend(["--gcs-prefix", args.gcs_prefix])
    if args.models_dir:
        cli_args.extend(["--models-dir", args.models_dir])
    else:
        models_dir_default = _models_dir_default(_pick_default_comfy_home(args.version_id))
        cli_args.extend(["--models-dir", str(models_dir_default)])
    if args.verbose:
        cli_args.append("--verbose")

    try:
        return handler_main.main(cli_args)
    finally:
        if args.offline:
            if prev_offline is None:
                os.environ.pop("COMFY_OFFLINE", None)
            else:
                os.environ["COMFY_OFFLINE"] = prev_offline


def cmd_delete(args: argparse.Namespace) -> int:
    target_path = pathlib.Path(args.target).resolve() if args.target else _pick_default_comfy_home(args.version_id)
    removed_any = False
    if target_path.exists():
        print(f"[INFO] Удаляем окружение: {target_path}")
        shutil.rmtree(target_path)
        removed_any = True
    else:
        print(f"[WARN] Окружение не найдено: {target_path}")

    lock_path = _lock_path_for_version(args.version_id)
    if lock_path.exists():
        lock_path.unlink()
        removed_any = True
        print(f"[INFO] Удалён resolved-lock: {lock_path}")

    if args.remove_spec:
        try:
            spec_path = _resolve_spec_path(args.version_id)
        except FileNotFoundError:
            spec_path = None
        if spec_path and spec_path.exists():
            spec_path.unlink()
            removed_any = True
            print(f"[INFO] Удалена спецификация: {spec_path}")
        else:
            print("[WARN] Файл спецификации не найден")

    if not removed_any:
        print("[WARN] Нечего удалять")
    return 0


def cmd_clone(args: argparse.Namespace) -> int:
    try:
        source_path = _resolve_spec_path(args.source_version)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 2

    try:
        spec = json.loads(source_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[ERROR] Не удалось прочитать {source_path}: {exc}")
        return 2

    spec["version_id"] = args.new_version

    output_path = pathlib.Path(args.output).resolve() if args.output else (pathlib.Path("versions") / f"{args.new_version}.json")
    if output_path.exists() and not args.force:
        print(f"[ERROR] Файл {output_path} уже существует. Используйте --force для перезаписи.")
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[OK] Версия {args.source_version} клонирована в {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Version management CLI for schema v2 specs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_create = subparsers.add_parser("create", help="Generate versions/<id>.json spec from arguments")
    p_create.add_argument("version_id", help="Identifier for the version (used as versions/<id>.json)")
    p_create.add_argument("--repo", required=True, help="ComfyUI repo URL with optional @ref (e.g. https://...@main)")
    p_create.add_argument("--nodes", action="append", default=[], help="Custom node definition: JSON object/file or <repo>@<ref>")
    p_create.add_argument("--models", action="append", default=[], help="Model definition: JSON object or file with list")
    p_create.add_argument("--nodes-file", default=None, help="Path to JSON/YAML file with custom nodes list")
    p_create.add_argument("--models-file", default=None, help="Path to JSON/YAML file with models list")
    p_create.add_argument("--models-root", default=None, help="Base directory with local models for checksum auto-detect")
    p_create.add_argument("--auto-checksum", action="store_true", help="Automatically compute sha256 for local models")
    p_create.add_argument("--output", default=None, help="Explicit output path (default: versions/<version_id>.json)")
    p_create.set_defaults(func=cmd_create)

    p_resolve = subparsers.add_parser("resolve", help="Resolve refs to commits and save resolved-lock")
    p_resolve.add_argument("version_id", help="Version identifier (versions/<id>.json)")
    p_resolve.add_argument("--offline", action="store_true", help="Skip network operations when possible")
    p_resolve.set_defaults(func=cmd_resolve)

    p_realize = subparsers.add_parser("realize", help="Realize environment for version id")
    p_realize.add_argument("version_id", help="Version identifier (versions/<id>.json)")
    p_realize.add_argument("--target", help="Explicit COMFY_HOME path", default=None)
    p_realize.add_argument("--models-dir", help="Override MODELS_DIR", default=None)
    p_realize.add_argument("--wheels-dir", help="Directory with wheel files for offline install", default=None)
    p_realize.add_argument("--offline", action="store_true", help="Skip git/pip operations where possible")
    p_realize.add_argument("--dry-run", action="store_true", help="Show plan without changes")
    p_realize.set_defaults(func=cmd_realize)

    p_validate = subparsers.add_parser("validate", help="Validate spec and print resolved summary")
    p_validate.add_argument("version_id", help="Version identifier (versions/<id>.json)")
    p_validate.add_argument("--offline", action="store_true", help="Resolve without network calls")
    p_validate.set_defaults(func=cmd_validate)

    p_run_ui = subparsers.add_parser("run-ui", help="Realize and launch ComfyUI for version id")
    p_run_ui.add_argument("version_id", help="Version identifier (versions/<id>.json)")
    p_run_ui.add_argument("--target", help="Override COMFY_HOME path", default=None)
    p_run_ui.add_argument("--models-dir", help="Override MODELS_DIR", default=None)
    p_run_ui.add_argument("--wheels-dir", help="Directory with wheel files for offline install", default=None)
    p_run_ui.add_argument("--offline", action="store_true", help="Skip git/pip operations where possible")
    p_run_ui.add_argument("--host", default="0.0.0.0", help="Host for ComfyUI web server")
    p_run_ui.add_argument("--port", type=int, default=8188, help="Port for ComfyUI web server")
    p_run_ui.add_argument("--extra-args", nargs=argparse.REMAINDER, help="Additional args passed to ComfyUI (use -- to separate)")
    p_run_ui.set_defaults(func=cmd_run_ui)

    p_run_handler = subparsers.add_parser("run-handler", help="Run handler workflow for version id")
    p_run_handler.add_argument("version_id", help="Version identifier (versions/<id>.json)")
    p_run_handler.add_argument("--workflow", required=True, help="Path to workflow JSON")
    p_run_handler.add_argument("--output", choices=["base64", "gcs"], default="base64", help="Output mode")
    p_run_handler.add_argument("--out-file", default=None, help="Write base64 output to file")
    p_run_handler.add_argument("--gcs-bucket", default=os.environ.get("GCS_BUCKET"), help="GCS bucket for outputs")
    p_run_handler.add_argument("--gcs-prefix", default=os.environ.get("GCS_PREFIX", "comfy/outputs"), help="Prefix inside bucket")
    p_run_handler.add_argument("--models-dir", default=None, help="Override MODELS_DIR for handler")
    p_run_handler.add_argument("--verbose", action="store_true", help="Verbose logs")
    p_run_handler.add_argument("--offline", action="store_true", help="Set COMFY_OFFLINE=1 during execution")
    p_run_handler.set_defaults(func=cmd_run_handler)

    p_delete = subparsers.add_parser("delete", help="Remove realized environment and resolved lock for version")
    p_delete.add_argument("version_id", help="Version identifier (versions/<id>.json)")
    p_delete.add_argument("--target", default=None, help="Explicit COMFY_HOME to remove")
    p_delete.add_argument("--remove-spec", action="store_true", help="Delete versions/<id>.json as well")
    p_delete.set_defaults(func=cmd_delete)

    p_clone = subparsers.add_parser("clone", help="Clone spec to new version id")
    p_clone.add_argument("source_version", help="Existing version identifier")
    p_clone.add_argument("new_version", help="New version identifier")
    p_clone.add_argument("--output", default=None, help="Explicit output path (default: versions/<new>.json)")
    p_clone.add_argument("--force", action="store_true", help="Overwrite existing output")
    p_clone.set_defaults(func=cmd_clone)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

