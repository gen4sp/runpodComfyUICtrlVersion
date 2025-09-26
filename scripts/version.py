#!/usr/bin/env python3
"""Unified CLI for schema v2 version workflows."""

from __future__ import annotations

import argparse
import os
import pathlib
from typing import Optional

from rp_handler import main as handler_main
from rp_handler.main import spec_path_for_version
from rp_handler.resolver import (
    SpecValidationError,
    resolve_version_spec,
    save_resolved_lock,
    realize_from_resolved,
    _pick_default_comfy_home,
    _models_dir_default,
)


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


def cmd_test(args: argparse.Namespace) -> int:
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
    return handler_main.main(cli_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Version management CLI for schema v2 specs")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    p_test = subparsers.add_parser("test", help="Smoke-test workflow execution for version id")
    p_test.add_argument("version_id", help="Version identifier (versions/<id>.json)")
    p_test.add_argument("--workflow", required=True, help="Path to workflow JSON")
    p_test.add_argument("--output", choices=["base64", "gcs"], default="base64", help="Output mode for handler")
    p_test.add_argument("--out-file", default=None, help="Write base64 output to file")
    p_test.add_argument("--gcs-bucket", default=os.environ.get("GCS_BUCKET"), help="GCS bucket for outputs")
    p_test.add_argument("--gcs-prefix", default=os.environ.get("GCS_PREFIX", "comfy/outputs"), help="Prefix inside bucket")
    p_test.add_argument("--models-dir", default=None, help="Override MODELS_DIR for handler")
    p_test.add_argument("--verbose", action="store_true", help="Verbose logs")
    p_test.set_defaults(func=cmd_test)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

