#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
from typing import Any, Dict, Optional

from .resolver import (
    apply_lock_and_prepare,  # legacy (no longer used)
    resolve_version_spec,
    save_resolved_lock,
    realize_from_resolved,
)
from .output import emit_output
from .workflow import run_workflow
from .utils import validate_required_path


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RunPod ComfyUI handler (CLI)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--version-id", dest="version_id", required=False, default=None, help="Version id (loads versions/<id>.json)")
    g.add_argument("--spec", dest="spec_path", required=False, default=None, help="Path to version spec JSON (versions/<id>.json)")
    p.add_argument("--workflow", required=False, default=None, help="Path to ComfyUI workflow JSON (graph)")
    p.add_argument("--output", choices=["base64", "gcs"], default=os.environ.get("OUTPUT_MODE", "gcs"), help="How to return result")
    p.add_argument("--out-file", default=None, help="Optional path to write base64 output")
    p.add_argument("--gcs-bucket", default=os.environ.get("GCS_BUCKET"), help="Target GCS bucket for uploads")
    p.add_argument("--gcs-prefix", default=os.environ.get("GCS_PREFIX", "comfy/outputs"), help="Prefix inside the bucket")
    p.add_argument("--models-dir", default=os.environ.get("MODELS_DIR"), help="Base models dir override (optional)")
    p.add_argument("--verbose", action="store_true", help="Verbose logs")
    return p


def run_workflow_real(workflow_path: Optional[str], comfy_home: str, models_dir: str, verbose: bool) -> bytes:
    """Выполнить реальный workflow через ComfyUI."""
    if not workflow_path:
        # Если workflow не указан, возвращаем заглушку
        transparent_png_base64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
        )
        return base64.b64decode(transparent_png_base64)
    
    # Валидируем входные данные
    validate_required_path(workflow_path, "Workflow file")
    validate_required_path(comfy_home, "ComfyUI home directory")
    validate_required_path(models_dir, "Models directory")
    
    # Выполняем workflow
    return run_workflow(workflow_path, comfy_home, models_dir, verbose)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # 1) Resolve + realize version from spec (schema v2)
    if not args.version_id and not args.spec_path:
        parser.error("Provide either --version-id or --spec")

    # Determine spec path
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    if args.spec_path:
        spec_path = pathlib.Path(args.spec_path)
        if not spec_path.is_absolute():
            spec_path = (repo_root / spec_path).resolve()
    else:
        spec_path = (repo_root / "versions" / f"{args.version_id}.json").resolve()

    if not spec_path.exists():
        raise RuntimeError(f"Spec file not found: {spec_path}")

    # Offline behavior may be specified in spec.options.offline or env COMFY_OFFLINE
    offline_env = str(os.environ.get("COMFY_OFFLINE", "")).strip().lower() in {"1", "true", "yes", "on"}
    resolved = resolve_version_spec(spec_path, offline=offline_env)
    save_resolved_lock(resolved)
    comfy_home_path, models_dir_path = realize_from_resolved(resolved, offline=offline_env)

    # If user requested explicit models dir override, honor it
    models_dir_effective = pathlib.Path(args.models_dir).resolve() if args.models_dir else models_dir_path

    # 2) Выполнить воркфлоу через реальный раннер
    artifact_bytes = run_workflow_real(args.workflow, str(comfy_home_path), str(models_dir_effective), args.verbose)

    # 3) Эмит результата
    emit_output(
        data=artifact_bytes,
        mode=args.output,
        out_file=args.out_file,
        gcs_bucket=args.gcs_bucket,
        gcs_prefix=args.gcs_prefix,
        verbose=args.verbose,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())



