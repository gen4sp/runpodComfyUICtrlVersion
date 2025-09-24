#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
from typing import Any, Dict, Optional

from .resolver import apply_lock_and_prepare
from .output import emit_output
from .workflow import run_workflow
from .utils import validate_required_path


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RunPod ComfyUI handler (CLI)")
    p.add_argument("--lock", required=False, default=os.environ.get("LOCK_PATH"), help="Path to lock file (JSON)")
    p.add_argument("--workflow", required=False, default=None, help="Path to ComfyUI workflow JSON (graph)")
    p.add_argument("--output", choices=["base64", "gcs"], default=os.environ.get("OUTPUT_MODE", "gcs"), help="How to return result")
    p.add_argument("--out-file", default=None, help="Optional path to write base64 output")
    p.add_argument("--gcs-bucket", default=os.environ.get("GCS_BUCKET"), help="Target GCS bucket for uploads")
    p.add_argument("--gcs-prefix", default=os.environ.get("GCS_PREFIX", "comfy/outputs"), help="Prefix inside the bucket")
    p.add_argument("--models-dir", default=os.environ.get("MODELS_DIR"), help="Base models dir for resolver")
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

    # 1) Применить lock-файл: подготовить окружение, проверить модели
    apply_lock_and_prepare(lock_path=args.lock, models_dir=args.models_dir, verbose=args.verbose)

    # 2) Выполнить воркфлоу через реальный раннер
    comfy_home = os.environ.get("COMFY_HOME", "/opt/comfy")
    models_dir = args.models_dir or os.environ.get("MODELS_DIR", f"{comfy_home}/models")
    artifact_bytes = run_workflow_real(args.workflow, comfy_home, models_dir, args.verbose)

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



