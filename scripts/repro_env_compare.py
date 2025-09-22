#!/usr/bin/env python3
"""
Reproduce environment twice from the same lock file and compare:
- ComfyUI commit SHA
- Custom nodes commit SHA (or directory digest if not a git repo)
- Model file checksums (sha256)

Exit codes:
  0 - environments match
  1 - mismatch detected
  2 - unexpected error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_warn(message: str) -> None:
    print(f"[WARN] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def run_command(command: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    proc = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    return proc.returncode, out.strip(), err.strip()


def compute_file_sha256(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_dir_digest(path: str) -> str:
    """Compute stable sha256 digest of all files' contents and relative paths."""
    h = hashlib.sha256()
    root = pathlib.Path(path)
    if not root.exists():
        return ""
    files: List[pathlib.Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            files.append(p)
    files.sort(key=lambda p: str(p.relative_to(root)))
    for p in files:
        rel = str(p.relative_to(root)).encode("utf-8")
        h.update(rel)
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def expand_env(path: str, comfy_home: str, models_dir: Optional[str] = None) -> str:
    expanded = path.replace("$COMFY_HOME", comfy_home)
    expanded = expanded.replace("$MODELS_DIR", models_dir or str(pathlib.Path(comfy_home) / "models"))
    return os.path.expandvars(expanded)


def load_lock_models(lock_path: str) -> List[Dict[str, object]]:
    with open(lock_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    models = data.get("models", [])
    if not isinstance(models, list):
        return []
    normalized: List[Dict[str, object]] = []
    for m in models:
        if not isinstance(m, dict):
            continue
        normalized.append({
            "name": str(m.get("name") or m.get("id") or "model"),
            "target_path": str(m.get("target_path") or m.get("path") or ""),
        })
    return normalized


def GitHead(repo_dir: str) -> str:
    code, out, err = run_command(["git", "rev-parse", "HEAD"], cwd=repo_dir)
    if code != 0:
        return ""
    return out.strip()


def collect_env_facts(target_home: str, lock_path: str) -> Dict[str, object]:
    facts: Dict[str, object] = {}
    comfy_repo = pathlib.Path(target_home) / "ComfyUI"
    facts["comfyui_head"] = GitHead(str(comfy_repo)) if (comfy_repo / ".git").exists() else compute_dir_digest(str(comfy_repo))

    # custom nodes
    custom_nodes_dir = comfy_repo / "custom_nodes"
    nodes: Dict[str, str] = {}
    if custom_nodes_dir.exists():
        for child in custom_nodes_dir.iterdir():
            if not child.is_dir():
                continue
            head = GitHead(str(child)) if (child / ".git").exists() else compute_dir_digest(str(child))
            nodes[child.name] = head
    facts["custom_nodes"] = nodes

    # models
    models_facts: Dict[str, str] = {}
    for m in load_lock_models(lock_path):
        name = str(m.get("name"))
        raw_path = str(m.get("target_path"))
        if not raw_path:
            continue
        path = expand_env(raw_path, comfy_home=target_home)
        if os.path.exists(path):
            models_facts[name] = compute_file_sha256(path)
        else:
            models_facts[name] = "<missing>"
    facts["models"] = models_facts
    return facts


def compare_dicts(a: Dict[str, str], b: Dict[str, str]) -> List[str]:
    diffs: List[str] = []
    keys = sorted(set(a.keys()) | set(b.keys()))
    for k in keys:
        va = a.get(k, "<absent>")
        vb = b.get(k, "<absent>")
        if va != vb:
            diffs.append(f"{k}: {va} != {vb}")
    return diffs


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reproduce env twice and compare SHAs/checksums")
    p.add_argument("--lock", required=True, help="Path to lock file")
    p.add_argument("--python", default=os.environ.get("PYTHON_BIN", "python3"), help="Python for clone script")
    p.add_argument("--offline", action="store_true", help="Offline install for clone script")
    p.add_argument("--wheels-dir", default=None, help="Wheels directory for offline mode")
    p.add_argument("--pip-extra-args", default=None, help="Extra pip args for clone script")
    p.add_argument("--keep", action="store_true", help="Keep temporary directories")
    p.add_argument("--verbose", action="store_true")
    return p


def run_clone(lock_path: str, target_home: str, python_bin: str, offline: bool, wheels_dir: Optional[str], pip_extra_args: Optional[str], verbose: bool) -> None:
    script = str(pathlib.Path(__file__).with_name("clone_version.sh"))
    args: List[str] = [script, "--lock", lock_path, "--target", target_home, "--python", python_bin]
    if offline:
        args.append("--offline")
        if wheels_dir:
            args.extend(["--wheels-dir", wheels_dir])
    if pip_extra_args:
        args.extend(["--pip-extra-args", pip_extra_args])
    code, out, err = run_command(args, cwd=str(pathlib.Path(__file__).resolve().parent.parent))
    if verbose:
        print(out)
    if code != 0:
        raise RuntimeError(f"clone_version.sh failed: {err}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    tmp1 = tempfile.mkdtemp(prefix="comfy_env1_")
    tmp2 = tempfile.mkdtemp(prefix="comfy_env2_")
    try:
        log_info(f"Cloning to {tmp1}")
        run_clone(args.lock, tmp1, args.python, args.offline, args.wheels_dir, args.pip_extra_args, args.verbose)
        log_info(f"Cloning to {tmp2}")
        run_clone(args.lock, tmp2, args.python, args.offline, args.wheels_dir, args.pip_extra_args, args.verbose)

        log_info("Collecting facts from env #1")
        f1 = collect_env_facts(tmp1, args.lock)
        log_info("Collecting facts from env #2")
        f2 = collect_env_facts(tmp2, args.lock)

        mismatches: List[str] = []
        if f1.get("comfyui_head") != f2.get("comfyui_head"):
            mismatches.append(f"ComfyUI HEAD: {f1.get('comfyui_head')} != {f2.get('comfyui_head')}")

        mismatches += [f"custom_nodes.{d}" for d in compare_dicts(f1.get("custom_nodes", {}), f2.get("custom_nodes", {}))]
        mismatches += [f"models.{d}" for d in compare_dicts(f1.get("models", {}), f2.get("models", {}))]

        if mismatches:
            log_error("Mismatch detected:")
            for m in mismatches:
                print(" - " + m)
            return 1

        log_info("Environments match: commits and model checksums are identical")
        return 0
    except FileNotFoundError as exc:
        log_error(str(exc))
        return 2
    except Exception as exc:
        log_error(f"unexpected error: {exc}")
        return 2
    finally:
        if args.keep:
            log_info(f"Keeping directories: {tmp1}, {tmp2}")
        else:
            try:
                shutil.rmtree(tmp1, ignore_errors=True)
                shutil.rmtree(tmp2, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


