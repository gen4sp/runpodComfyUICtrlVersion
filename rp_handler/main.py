#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import pathlib
from typing import Optional

from .resolver import (
    SpecValidationError,
    resolve_version_spec,
    save_resolved_lock,
    realize_from_resolved,
)
from .output import emit_output
from .workflow import run_workflow
from .utils import validate_required_path


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def spec_path_for_version(version_id: str) -> pathlib.Path:
    version = version_id.strip()
    if not version:
        raise ValueError("Empty version id")
    return (_repo_root() / "versions" / f"{version}.json").resolve()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RunPod ComfyUI handler (CLI)")
    p.add_argument("--version-id", required=True, help="Version id (loads versions/<id>.json)")
    p.add_argument("--workflow", required=True, help="Path to ComfyUI workflow JSON (graph)")
    p.add_argument("--output", choices=["base64", "gcs"], default=os.environ.get("OUTPUT_MODE", "gcs"), help="How to return result")
    p.add_argument("--out-file", default=None, help="Optional path to write base64 output")
    p.add_argument("--gcs-bucket", default=os.environ.get("GCS_BUCKET"), help="Target GCS bucket for uploads")
    p.add_argument("--gcs-prefix", default=os.environ.get("GCS_PREFIX", "comfy/outputs"), help="Prefix inside the bucket")
    p.add_argument("--models-dir", default=os.environ.get("MODELS_DIR"), help="Base models dir override (optional)")
    p.add_argument("--verbose", action="store_true", help="Verbose logs")
    return p


def run_workflow_real(workflow_path: str, comfy_home: str, models_dir: str, verbose: bool) -> bytes:
    """Выполнить реальный workflow через ComfyUI."""
    validate_required_path(workflow_path, "Workflow file")
    validate_required_path(comfy_home, "ComfyUI home directory")
    validate_required_path(models_dir, "Models directory")

    return run_workflow(workflow_path, comfy_home, models_dir, verbose)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # 1) Resolve + realize version from spec (schema v2)
    try:
        spec_path = spec_path_for_version(args.version_id)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 2

    if not spec_path.exists():
        print(f"[ERROR] Spec file not found for version '{args.version_id}': {spec_path}")
        return 2

    # Offline behavior may be specified in spec.options.offline or env COMFY_OFFLINE
    offline_env = str(os.environ.get("COMFY_OFFLINE", "")).strip().lower() in {"1", "true", "yes", "on"}
    try:
        resolved = resolve_version_spec(spec_path, offline=offline_env)
    except SpecValidationError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 2

    resolved_options = resolved.get("options") or {}
    offline_effective = bool(resolved_options.get("offline") or offline_env)
    skip_models_effective = bool(resolved_options.get("skip_models"))
    resolved["options"] = {
        **resolved_options,
        "offline": offline_effective,
        "skip_models": skip_models_effective,
    }

    save_resolved_lock(resolved)
    comfy_home_path, models_dir_path = realize_from_resolved(resolved, offline=offline_effective)

    # If user requested explicit models dir override, honor it
    models_dir_effective = pathlib.Path(args.models_dir).resolve() if args.models_dir else models_dir_path

    # 2) Выполнить воркфлоу через реальный раннер
    try:
        artifact_bytes = run_workflow_real(args.workflow, str(comfy_home_path), str(models_dir_effective), args.verbose)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 2

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



