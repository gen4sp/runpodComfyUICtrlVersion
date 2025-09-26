#!/usr/bin/env python3
"""
Pin requirements from a flexible requirements.txt into a deterministic list for the lock file.

Features:
- Reads a requirements file (supports comments, -r includes, direct URLs, name==ver, name @ url)
- Resolves transitive versions using pip in a temporary isolated environment (optional)
- Outputs a JSON snippet suitable for the "python.packages" section of the lock file
- Optionally writes back into an existing lock file, replacing the python.packages list
- Supports offline mode via a wheels directory (no index)

Usage examples:
  python3 scripts/pin_requirements.py \
    --requirements requirements.txt \
    --output versions/python-packages.json

  python3 scripts/pin_requirements.py \
    --requirements requirements.txt \
    --lock ~/.cache/runpod-comfy/resolved/comfy-foo.lock.json --in-place

Offline pinning using wheel artifacts:
  python3 scripts/pin_requirements.py \
    --requirements requirements.txt \
    --wheels-dir /path/to/wheels --offline \
    --lock ~/.cache/runpod-comfy/resolved/comfy-foo.lock.json --in-place
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, Iterable, List, Optional, Tuple


def run(cmd: List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out.strip(), err.strip()


def read_requirements(path: str) -> List[str]:
    path_obj = pathlib.Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"requirements file not found: {path}")
    lines: List[str] = []
    for raw in path_obj.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            inc = line.split(None, 1)[1]
            inc_path = str((path_obj.parent / inc).resolve())
            lines.extend(read_requirements(inc_path))
            continue
        lines.append(line)
    return lines


def create_isolated_env(base_python: str) -> Tuple[str, str]:
    venv_dir = tempfile.mkdtemp(prefix="pinreq_venv_")
    code, _, err = run([base_python, "-m", "venv", venv_dir])
    if code != 0:
        raise RuntimeError(f"failed to create venv: {err}")
    python = str(pathlib.Path(venv_dir) / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    code, _, err = run([python, "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
    if code != 0:
        raise RuntimeError(f"failed to bootstrap pip: {err}")
    return venv_dir, python


def freeze_pins(python: str, req_lines: List[str], offline: bool, wheels_dir: Optional[str], extra_pip_args: List[str]) -> List[str]:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as tmp:
        tmp.write("\n".join(req_lines) + "\n")
        req_path = tmp.name
    pip_cmd = [python, "-m", "pip", "install"]
    if offline:
        if wheels_dir:
            pip_cmd += ["--no-index", "--find-links", wheels_dir]
        else:
            pip_cmd += ["--no-index"]
    pip_cmd += extra_pip_args
    pip_cmd += ["-r", req_path]
    code, _, err = run(pip_cmd)
    if code != 0:
        raise RuntimeError(f"pip install failed: {err}")
    code, out, err = run([python, "-m", "pip", "freeze"])
    if code != 0:
        raise RuntimeError(f"pip freeze failed: {err}")
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines


def parse_freeze_line(line: str) -> Optional[Dict[str, Optional[str]]]:
    if line.startswith("-e "):
        return None
    if " @ " in line:
        name, url = line.split(" @ ", 1)
        return {"name": name.strip(), "version": None, "url": url.strip()}
    if "==" in line:
        name, ver = line.split("==", 1)
        return {"name": name.strip(), "version": ver.strip(), "url": None}
    if "===" in line:
        name, ver = line.split("===", 1)
        return {"name": name.strip(), "version": ver.strip(), "url": None}
    return None


def to_lock_packages(freeze_lines: List[str], wheel_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []
    wheel_map = wheel_map or {}
    for raw in freeze_lines:
        parsed = parse_freeze_line(raw)
        if not parsed:
            continue
        name = parsed.get("name") or ""
        # Prefer explicit mapping over parsed URL
        if name in wheel_map:
            parsed["url"] = wheel_map[name]
        out.append(parsed)
    out.sort(key=lambda d: str(d["name"]).lower())
    return out


def write_output(packages: List[Dict[str, Optional[str]]], output: Optional[str], lock_path: Optional[str], in_place: bool, pretty: bool) -> None:
    if lock_path:
        path = pathlib.Path(lock_path)
        if not path.exists():
            raise FileNotFoundError(f"lock file not found: {lock_path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        py = data.get("python", {})
        py["packages"] = packages
        data["python"] = py
        text = json.dumps(data, indent=(2 if pretty else None), sort_keys=True, ensure_ascii=False)
        if in_place:
            path.write_text(text, encoding="utf-8")
        else:
            print(text)
        return
    payload = {"packages": packages}
    text = json.dumps(payload, indent=(2 if pretty else None), sort_keys=True, ensure_ascii=False)
    if output:
        outp = pathlib.Path(output)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(text, encoding="utf-8")
    else:
        print(text)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Pin requirements to lock packages")
    p.add_argument("--requirements", required=True, help="Path to requirements.txt (can include -r includes)")
    p.add_argument("--python", default=sys.executable, help="Base python interpreter to spawn isolated venv")
    p.add_argument("--offline", action="store_true", help="Do not use indexes; rely on wheels-dir or pip cache")
    p.add_argument("--wheels-dir", default=None, help="Directory with wheel artifacts for offline installs")
    p.add_argument("--pip-extra-args", default=None, help="Extra args passed to pip install (quoted)")
    p.add_argument("--lock", default=None, help="Path to existing lock file to update")
    p.add_argument("--wheel-url", dest="wheel_urls", action="append", default=[], help="Optional mapping name=url; can repeat")
    p.add_argument("--in-place", action="store_true", help="Write back into --lock instead of printing")
    p.add_argument("--output", default=None, help="Output path for JSON (if not using --lock)")
    p.add_argument("--pretty", action="store_true", help="Pretty JSON output")
    args = p.parse_args(argv)

    req_lines = read_requirements(args.requirements)
    venv_dir, py = create_isolated_env(args.python)
    try:
        extra = []
        if args.pip_extra_args:
            # naive split, acceptable for common cases
            extra = args.pip_extra_args.split()
        frozen = freeze_pins(py, req_lines, offline=args.offline, wheels_dir=args.wheels_dir, extra_pip_args=extra)
        wheel_map: Dict[str, str] = {}
        for entry in args.wheel_urls:
            if "=" in entry:
                k, v = entry.split("=", 1)
                wheel_map[k.strip()] = v.strip()
        packages = to_lock_packages(frozen, wheel_map=wheel_map)
        write_output(packages, output=args.output, lock_path=args.lock, in_place=args.in_place, pretty=args.pretty)
    finally:
        try:
            shutil.rmtree(venv_dir, ignore_errors=True)
        except Exception:
            pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


