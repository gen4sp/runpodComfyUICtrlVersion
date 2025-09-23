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
import json
import os
import pathlib
import subprocess
import sys
from typing import Optional, Tuple


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_error(msg: str) -> None:
    print(f"[ERROR] {msg}")


def run_handler(lock: str, workflow: str, output_mode: str = "base64") -> Tuple[int, str, str]:
    root = pathlib.Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "rp_handler.main", "--lock", lock, "--workflow", workflow, "--output", output_mode]
    proc = subprocess.Popen(cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    return proc.returncode, out.strip(), err.strip()


def compute_hash_of_stdout_b64(b64_text: str) -> str:
    # Hash the decoded bytes of base64
    import base64
    data = base64.b64decode(b64_text)
    return hashlib.sha256(data).hexdigest()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run workflow and compare artifact hash with baseline")
    p.add_argument("--lock", required=True, help="Path to lock file")
    p.add_argument("--workflow", required=True, help="Path to workflow JSON")
    p.add_argument("--baseline", required=True, help="Path to baseline JSON file")
    p.add_argument("--mode", choices=["record", "compare"], default="compare")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Force base64 output for hashing deterministically via stdout
    code, out, err = run_handler(args.lock, args.workflow, output_mode="base64")
    if code != 0:
        log_error(f"handler failed: {err}")
        return 2
    artifact_hash = compute_hash_of_stdout_b64(out)

    baseline_path = pathlib.Path(args.baseline)
    if args.mode == "record":
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_data = {"artifact_sha256": artifact_hash}
        baseline_path.write_text(json.dumps(baseline_data, indent=2, sort_keys=True), encoding="utf-8")
        log_info(f"Recorded baseline hash to {baseline_path}")
        return 0

    # compare
    if not baseline_path.exists():
        log_error(f"baseline not found: {baseline_path}")
        return 2
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline_hash = str(baseline.get("artifact_sha256") or "")
    except Exception as exc:
        log_error(f"invalid baseline file: {exc}")
        return 2

    if not baseline_hash:
        log_error("empty baseline hash")
        return 2

    if artifact_hash == baseline_hash:
        log_info("Artifact matches baseline")
        return 0
    else:
        log_error(f"Artifact differs: {artifact_hash} != {baseline_hash}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


