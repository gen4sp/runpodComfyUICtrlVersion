#!/usr/bin/env python3
"""
Развёртка версии ComfyUI по новой спецификации `versions/*.json` (schema_version=2).

Поведение:
-   Резолвит `ref` → `commit`, формирует resolved-lock в `~/.comfy-cache/resolved/<version_id>.lock.json`.
-   Готовит `COMFY_HOME` c отдельным `.venv`, клонирует ComfyUI и кастом-ноды из кеша/репо.
-   (Опционально) выводит только план действий в режиме `--dry-run`.

Примеры использования:
  python3 scripts/realize_version.py --version-id wan22-fast
  python3 scripts/realize_version.py --spec versions/test-ver.json --dry-run
  python3 scripts/realize_version.py --version-id local --target /runpod-volume/comfy-local --models-dir /workspace/models
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import json
from typing import Dict, Optional

from rp_handler.resolver import (
    SpecValidationError,
    resolve_version_spec,
    save_resolved_lock,
    realize_from_resolved,
)


def _repo_root() -> pathlib.Path:
    # repo root = parent of scripts directory
    return pathlib.Path(__file__).resolve().parent.parent


def _file_exists(p: pathlib.Path) -> bool:
    try:
        return p.exists()
    except Exception:
        return False


def _pick_default_target(version_id: str) -> pathlib.Path:
    # Prefer RunPod volume if present
    runpod_vol = pathlib.Path("/runpod-volume")
    if _file_exists(runpod_vol) and runpod_vol.is_dir():
        return runpod_vol / f"comfy-{version_id}"
    # Prefer HOME if available
    home = os.environ.get("HOME")
    if home:
        return pathlib.Path(home) / f"comfy-{version_id}"
    # Fallback to cwd
    return pathlib.Path.cwd() / f"comfy-{version_id}"


def _resolve_path(base: pathlib.Path, maybe_path: str) -> pathlib.Path:
    p = pathlib.Path(maybe_path)
    if p.is_absolute():
        return p
    # Try relative to provided base, then cwd
    candidate = (base / p).resolve()
    if _file_exists(candidate):
        return candidate
    return (pathlib.Path.cwd() / p).resolve()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Развернуть версию ComfyUI по спецификации schema v2")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--version-id", dest="version_id", help="Загрузить versions/<id>.json")
    g.add_argument("--spec", dest="spec_path", help="Путь к произвольной версии JSON")
    p.add_argument("--target", dest="target_path", default=None, help="Желаемый COMFY_HOME для развёртки")
    p.add_argument("--models-dir", dest="models_dir", default=None, help="Явный MODELS_DIR (по умолчанию из resolved)")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="Только показать план действий")
    p.add_argument("--offline", dest="offline", action="store_true", help="Не выполнять git/pip операции")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    repo_root = _repo_root()

    # Resolve spec path
    spec_path: Optional[pathlib.Path] = None
    if args.spec_path:
        spec_path = _resolve_path(repo_root, args.spec_path)
    elif args.version_id:
        spec_path = repo_root / "versions" / f"{args.version_id}.json"
    else:
        parser.error("Нужен --version-id или --spec")

    version_id: Optional[str] = args.version_id
    spec_data: Dict[str, object] = {}
    if spec_path is None or not _file_exists(spec_path):
        print(f"[ERROR] Spec file not found: {spec_path}")
        return 2
    try:
        spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[ERROR] Failed to read spec {spec_path}: {exc}")
        return 2
    if not version_id:
        version_id_raw = spec_data.get("version_id") or spec_data.get("id")
        if isinstance(version_id_raw, str) and version_id_raw.strip():
            version_id = version_id_raw.strip()
    if not version_id:
        version_id = "version"

    # Target path selection
    target_from_cli = args.target_path
    target_from_spec = None
    if isinstance(spec_data, dict):
        t = spec_data.get("target")
        if isinstance(t, str) and t.strip():
            target_from_spec = t
    if target_from_cli:
        target_path = _resolve_path(pathlib.Path.cwd(), target_from_cli)
    elif target_from_spec:
        target_path = _resolve_path(pathlib.Path.cwd(), target_from_spec)
    else:
        comfy_home_env = os.environ.get("COMFY_HOME")
        if comfy_home_env:
            print(f"[WARN] COMFY_HOME is set: {comfy_home_env}. Используем изолированную директорию версии")
        target_path = _pick_default_target(version_id)

    # Resolve + realize spec
    offline_requested = bool(args.offline)
    resolved: Dict[str, object]
    try:
        resolved = resolve_version_spec(spec_path, offline=offline_requested)
    except SpecValidationError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 2

    resolved_options = resolved.get("options") if isinstance(resolved, dict) else {}
    if not isinstance(resolved_options, dict):
        resolved_options = {}
    effective_offline = bool(resolved_options.get("offline") or offline_requested)
    if effective_offline:
        print("[INFO] Offline режим: git/pip операции будут пропущены там, где возможно")

    models_dir_override = args.models_dir or None

    summary_lines = [
        f"  version_id:  {resolved.get('version_id')}",
    ]
    comfy = resolved.get("comfy", {}) if isinstance(resolved, dict) else {}
    if isinstance(comfy, dict):
        summary_lines.append(f"  comfy.repo:  {comfy.get('repo')}")
        summary_lines.append(f"  comfy.ref:   {comfy.get('ref')}")
        summary_lines.append(f"  comfy.commit:{comfy.get('commit')}")
    summary_lines.append(f"  target:      {target_path}")
    summary_lines.append(f"  offline:     {effective_offline}")
    if models_dir_override:
        summary_lines.append(f"  models_dir:  {models_dir_override}")

    custom_nodes = resolved.get("custom_nodes")
    if isinstance(custom_nodes, list) and custom_nodes:
        summary_lines.append("  custom_nodes:")
        for node in custom_nodes:
            if not isinstance(node, dict):
                continue
            summary_lines.append(
                f"    - {node.get('name') or node.get('repo')} (commit: {node.get('commit')})"
            )

    models = resolved.get("models")
    if isinstance(models, list) and models:
        summary_lines.append("  models:")
        for model in models:
            if not isinstance(model, dict):
                continue
            summary_lines.append(
                f"    - {model.get('name') or model.get('source')} -> {model.get('target_subdir') or '-'}"
            )

    print("[INFO] План развёртки:")
    for line in summary_lines:
        print(line)

    if args.dry_run:
        print("[DRY-RUN] Завершено без изменений")
        return 0

    save_resolved_lock(resolved)

    comfy_home, default_models_dir = realize_from_resolved(resolved, offline=effective_offline)
    models_dir_effective = pathlib.Path(models_dir_override).resolve() if models_dir_override else default_models_dir

    print("[OK] Версия готова")
    print(f"  COMFY_HOME: {comfy_home}")
    print(f"  MODELS_DIR: {models_dir_effective}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


