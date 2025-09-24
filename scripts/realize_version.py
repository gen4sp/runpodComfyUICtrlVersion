#!/usr/bin/env python3
"""
Realize (deploy) a ComfyUI version from a simple JSON spec in versions/.

Spec format (versions/<id>.json):
{
  "version_id": "wan22-fast",
  "lock": "lockfiles/comfy-wan2.2.lock.json",
  "target": "/runpod-volume/comfy-wan22-fast",      # optional; default is auto
  "options": {
    "offline": false,                                 # optional
    "skip_models": false,                             # optional
    "wheels_dir": "/wheels",                        # optional
    "pip_extra_args": "--no-cache-dir"               # optional
  }
}

Behavior:
- Resolves lock path (absolute) relative to repo root or current working dir
- Chooses target path in priority: CLI --target > spec.target > env COMFY_HOME (warn) >
  /runpod-volume/comfy-<version_id> if /runpod-volume exists > $HOME/comfy-<version_id> > ./comfy-<version_id>
- Invokes scripts/clone_version.sh with composed flags to create per-version COMFY_HOME
  (separate .venv, ComfyUI clone, custom_nodes, pinned python packages, models)

Usage examples:
  python3 scripts/realize_version.py --version-id wan22-fast
  python3 scripts/realize_version.py --spec versions/wan22-fast.json --offline
  python3 scripts/realize_version.py --version-id local --target "$HOME/comfy-local"
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Dict, Optional, Tuple


def _repo_root() -> pathlib.Path:
    # repo root = parent of scripts directory
    return pathlib.Path(__file__).resolve().parent.parent


def _file_exists(p: pathlib.Path) -> bool:
    try:
        return p.exists()
    except Exception:
        return False


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _run(cmd: list[str]) -> Tuple[int, str, str]:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    return proc.returncode, out.strip(), err.strip()


def _read_json(path: pathlib.Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    p = argparse.ArgumentParser(description="Realize a ComfyUI version from versions/<id>.json")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--version-id", dest="version_id", help="Version id (loads versions/<id>.json)")
    g.add_argument("--spec", dest="spec_path", help="Path to version spec JSON (versions/<id>.json)")
    p.add_argument("--lock", dest="lock_path", default=None, help="Explicit lock path; overrides spec.lock")
    p.add_argument("--target", dest="target_path", default=None, help="Explicit target COMFY_HOME; overrides spec.target")
    p.add_argument("--python", dest="python_bin", default=None, help="Python used by clone script during setup")
    p.add_argument("--offline", dest="offline", action="store_true", help="Offline install (use --wheels-dir)")
    p.add_argument("--skip-models", dest="skip_models", action="store_true", help="Skip model verification/fetch")
    p.add_argument("--wheels-dir", dest="wheels_dir", default=None, help="Local wheels dir for offline mode")
    p.add_argument("--pip-extra-args", dest="pip_extra_args", default=None, help="Extra args passed to pip install")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="Print actions only, do not execute")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    scripts_dir = repo_root / "scripts"
    clone_script = scripts_dir / "clone_version.sh"
    if not _file_exists(clone_script):
        print(f"[ERROR] clone_version.sh not found at {clone_script}")
        return 2

    # Resolve spec path
    spec_path: Optional[pathlib.Path] = None
    if args.spec_path:
        spec_path = _resolve_path(repo_root, args.spec_path)
    elif args.version_id:
        spec_path = repo_root / "versions" / f"{args.version_id}.json"
    else:
        # If lock is passed explicitly, spec is optional
        if not args.lock_path:
            parser.error("Provide either --version-id, --spec, or --lock")

    version_id: Optional[str] = args.version_id
    spec: Dict[str, object] = {}
    if spec_path is not None:
        if not _file_exists(spec_path):
            print(f"[ERROR] Spec file not found: {spec_path}")
            return 2
        spec = _read_json(spec_path)
        if not version_id:
            version_id = str(spec.get("version_id") or spec.get("id") or "") or None
    if not version_id:
        # Derive from lock file name if possible
        if args.lock_path:
            tail = pathlib.Path(args.lock_path).stem  # comfy-<name>.lock
            if tail.startswith("comfy-") and tail.endswith(".lock"):
                version_id = tail[len("comfy-") : -len(".lock")]
        if not version_id:
            version_id = "version"

    # Resolve lock path
    lock_from_cli = args.lock_path
    lock_from_spec = spec.get("lock") if isinstance(spec, dict) else None
    if lock_from_spec is not None and not isinstance(lock_from_spec, str):
        print("[ERROR] spec.lock must be a string path")
        return 2
    lock_value = lock_from_cli or lock_from_spec
    if not lock_value:
        print("[ERROR] Lock path is required (via --lock or spec.lock)")
        return 2
    lock_path = _resolve_path(repo_root, str(lock_value))
    if not _file_exists(lock_path):
        print(f"[ERROR] Lock file not found: {lock_path}")
        return 2

    # Target path selection
    target_from_cli = args.target_path
    target_from_spec = None
    if isinstance(spec, dict):
        t = spec.get("target")
        if isinstance(t, str) and t.strip():
            target_from_spec = t
    if target_from_cli:
        target_path = _resolve_path(pathlib.Path.cwd(), target_from_cli)
    elif target_from_spec:
        target_path = _resolve_path(pathlib.Path.cwd(), target_from_spec)
    else:
        # Warn if COMFY_HOME would collapse multiple versions into single venv
        comfy_home_env = os.environ.get("COMFY_HOME")
        if comfy_home_env:
            print(f"[WARN] COMFY_HOME is set: {comfy_home_env}. Using separate per-version directory instead.")
        target_path = _pick_default_target(version_id)

    # Compose clone command
    cmd: list[str] = ["bash", str(clone_script), "--lock", str(lock_path), "--target", str(target_path)]
    if args.python_bin:
        cmd += ["--python", args.python_bin]
    # Merge options from spec.options
    options = spec.get("options") if isinstance(spec, dict) else None
    if isinstance(options, dict):
        if options.get("offline") is True and not args.offline:
            args.offline = True
        if options.get("skip_models") is True and not args.skip_models:
            args.skip_models = True
        if isinstance(options.get("wheels_dir"), str) and not args.wheels_dir:
            args.wheels_dir = str(options["wheels_dir"])  # type: ignore[index]
        if isinstance(options.get("pip_extra_args"), str) and not args.pip_extra_args:
            args.pip_extra_args = str(options["pip_extra_args"])  # type: ignore[index]

    if args.skip_models:
        cmd.append("--skip-models")
    if args.offline:
        cmd.append("--offline")
    if args.wheels_dir:
        cmd += ["--wheels-dir", args.wheels_dir]
    if args.pip_extra_args:
        cmd += ["--pip-extra-args", args.pip_extra_args]

    print("[INFO] Realizing version:")
    print(f"  version_id: {version_id}")
    print(f"  lock:       {lock_path}")
    print(f"  target:     {target_path}")
    if args.offline:
        print("  offline:    true")
    if args.skip_models:
        print("  skip_models:true")
    if args.wheels_dir:
        print(f"  wheels_dir: {args.wheels_dir}")
    if args.pip_extra_args:
        print(f"  pip_extra:  {args.pip_extra_args}")

    if args.dry_run:
        print("[DRY-RUN] Would execute:")
        print("  ", " ".join(cmd))
        return 0

    # Execute clone
    code, out, err = _run(cmd)
    if code != 0:
        print(f"[ERROR] clone_version failed ({code}): {err or out}")
        return code or 1
    print(out)
    print("[OK] Version realized at:", str(target_path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


