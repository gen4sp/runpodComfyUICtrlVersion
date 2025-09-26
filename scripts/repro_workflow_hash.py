#!/usr/bin/env python3
"""
Run a workflow via handler and compute artifact hash to compare with a baseline.

Modes:
 - record: run and save baseline hash to file
 - compare: run and compare with existing baseline; exit 0 if equal, 1 if different

The handler inside this repo is a dummy that returns PNG bytes or workflow content.
When integrated with real ComfyUI execution, artifact bytes should be the
generated image or output payload.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import subprocess
import sys
from typing import Optional, Tuple


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_error(msg: str) -> None:
    print(f"[ERROR] {msg}")


def run_handler(version_id: str, workflow: str, output_mode: str = "base64", env: Optional[dict] = None) -> Tuple[int, str, str]:
    root = pathlib.Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable,
        "-m",
        "rp_handler.main",
        "--version-id",
        version_id,
        "--workflow",
        workflow,
        "--output",
        output_mode,
    ]
    proc = subprocess.Popen(cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    out, err = proc.communicate()
    return proc.returncode, out.strip(), err.strip()


def compute_hash_of_stdout_b64(b64_text: str) -> str:
    # Hash the decoded bytes of base64
    import base64
    data = base64.b64decode(b64_text)
    return hashlib.sha256(data).hexdigest()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run workflow and compare artifact hash with baseline")
    p.add_argument("--version-id", required=True, help="Version id to resolve and run")
    p.add_argument("--workflow", required=True, help="Path to workflow JSON")
    p.add_argument("--baseline", required=True, help="Path to baseline hash file")
    p.add_argument("--mode", choices=["record", "compare"], default="compare")
    p.add_argument("--models-dir", default=None, help="Override MODELS_DIR for handler")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    env = os.environ.copy()
    if args.models_dir:
        env["MODELS_DIR"] = args.models_dir

    # Force base64 output for hashing deterministically via stdout
    code, out, err = run_handler(args.version_id, args.workflow, output_mode="base64", env=env)
    if code != 0:
        log_error(f"handler failed: {err}")
        return 2
    artifact_hash = compute_hash_of_stdout_b64(out)

    baseline_path = pathlib.Path(args.baseline)
    if args.mode == "record":
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(artifact_hash + "\n", encoding="utf-8")
        log_info(f"Recorded baseline hash to {baseline_path}")
        return 0

    if not baseline_path.exists():
        log_error(f"baseline not found: {baseline_path}")
        return 2

    baseline_hash = baseline_path.read_text(encoding="utf-8").strip()
    if not baseline_hash:
        log_error("empty baseline hash")
        return 2

    if artifact_hash == baseline_hash:
        log_info("Artifact matches baseline")
        return 0

    log_error(f"Artifact differs: {artifact_hash} != {baseline_hash}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


