#!/usr/bin/env python3
"""
Create a deterministic lock file for a ComfyUI setup.

Outputs: lockfiles/comfy-<name>.lock.json

Content schema (beta):
{
  "version_name": str,
  "comfyui": {"repo": str | None, "commit": str | None, "path": str | None},
  "custom_nodes": [{"name": str, "repo": str | None, "commit": str | None, "path": str}],
  "python": {"version": str, "interpreter": str, "packages": [{"name": str, "version": str | None, "url": str | None}]},
  "models": [{"name": str, "source": str | None, "checksum": str | None, "target_path": str}],
  "schema_version": 1
}

Determinism:
- No timestamps in the output
- Sorted collections by stable keys
- Sorted JSON keys and stable separators
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
from typing import Dict, Iterable, List, Optional, Tuple


# ----------------------------- Small utilities ----------------------------- #


def run_command(command: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = process.communicate()
    return process.returncode, out.strip(), err.strip()


def which_python_in_venv(venv_path: Optional[str]) -> Optional[str]:
    if not venv_path:
        return None
    candidate = pathlib.Path(venv_path).expanduser().resolve() / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(candidate) if candidate.exists() else None


def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def safe_makedirs(path: str) -> None:
    pathlib.Path(path).mkdir(parents=True, exist_ok=True)


def expand_env(path: str, extra_env: Optional[Dict[str, str]] = None) -> str:
    if extra_env:
        # Construct a temporary env for expansion
        env = os.environ.copy()
        env.update(extra_env)
        return os.path.expandvars(path.replace("$COMFY_HOME", extra_env.get("COMFY_HOME", "")))
    return os.path.expandvars(path)


# ------------------------------- Git helpers ------------------------------- #


def is_git_repo(path: str) -> bool:
    code, _, _ = run_command(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
    return code == 0


def git_current_commit(path: str) -> Optional[str]:
    code, out, _ = run_command(["git", "rev-parse", "HEAD"], cwd=path)
    return out if code == 0 else None


def git_origin_url(path: str) -> Optional[str]:
    code, out, _ = run_command(["git", "remote", "get-url", "origin"], cwd=path)
    return out if code == 0 else None


def collect_repo_info(path: str, declared_repo_url: Optional[str] = None) -> Dict[str, Optional[str]]:
    repo_info: Dict[str, Optional[str]] = {
        "repo": None,
        "commit": None,
        "path": None,
    }
    repo_path = pathlib.Path(path).expanduser().resolve()
    repo_info["path"] = str(repo_path)
    if is_git_repo(str(repo_path)):
        repo_info["commit"] = git_current_commit(str(repo_path))
        repo_info["repo"] = declared_repo_url or git_origin_url(str(repo_path))
    else:
        # Non-git directory; leave commit None, path filled
        repo_info["repo"] = declared_repo_url
    return repo_info


# ----------------------------- Custom nodes scan ---------------------------- #


@dataclasses.dataclass
class CustomNode:
    name: str
    path: str
    repo: Optional[str]
    commit: Optional[str]


def discover_custom_nodes(custom_nodes_dir: str) -> List[CustomNode]:
    result: List[CustomNode] = []
    base = pathlib.Path(custom_nodes_dir).expanduser()
    if not base.exists() or not base.is_dir():
        return result
    for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        # Heuristic: consider a directory a node if it contains python files or a .git folder
        is_candidate = (child / ".git").exists()
        if not is_candidate:
            for py in child.glob("**/*.py"):
                is_candidate = True
                break
        if not is_candidate:
            continue
        repo_url = git_origin_url(str(child)) if is_git_repo(str(child)) else None
        commit = git_current_commit(str(child)) if is_git_repo(str(child)) else None
        result.append(CustomNode(name=child.name, path=str(child.resolve()), repo=repo_url, commit=commit))
    return result


def parse_kv_list(items: Iterable[str]) -> List[Dict[str, str]]:
    """Parse entries like "key=a,foo=b" into dicts."""
    parsed: List[Dict[str, str]] = []
    for item in items:
        entry: Dict[str, str] = {}
        for pair in item.split(","):
            if not pair.strip():
                continue
            if "=" not in pair:
                # allow positional style like name:repo-url (fallback)
                continue
            key, value = pair.split("=", 1)
            entry[key.strip()] = value.strip()
        if entry:
            parsed.append(entry)
    return parsed


def merge_custom_nodes(auto_nodes: List[CustomNode], manual_entries: List[Dict[str, str]]) -> List[CustomNode]:
    nodes_by_name: Dict[str, CustomNode] = {n.name: n for n in auto_nodes}
    for entry in manual_entries:
        name = entry.get("name") or entry.get("id")
        if not name:
            # Derive name from path or repo if possible
            derived = entry.get("path") or entry.get("repo") or "node"
            name = pathlib.Path(derived).stem
        path_value = entry.get("path")
        repo_value = entry.get("repo")
        commit_value = entry.get("commit")
        if path_value:
            repo_info = collect_repo_info(path_value, declared_repo_url=repo_value)
            node = CustomNode(
                name=name,
                path=repo_info.get("path") or path_value,
                repo=repo_info.get("repo") or repo_value,
                commit=repo_info.get("commit") or commit_value,
            )
        else:
            # No local path: we cannot derive commit without a checkout; keep repo/commit as provided
            node = CustomNode(name=name, path="", repo=repo_value, commit=commit_value)
        nodes_by_name[name] = node
    merged = list(nodes_by_name.values())
    merged.sort(key=lambda n: n.name.lower())
    return merged


# ---------------------------- Python dependencies --------------------------- #


@dataclasses.dataclass
class Package:
    name: str
    version: Optional[str] = None
    url: Optional[str] = None


def parse_freeze_line(line: str) -> Optional[Package]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("-e "):
        return None
    # pep 440 direct URL: name @ url
    if " @ " in line:
        name, url = line.split(" @ ", 1)
        return Package(name=name.strip(), url=url.strip())
    # simple name==version
    if "==" in line:
        name, version = line.split("==", 1)
        return Package(name=name.strip(), version=version.strip())
    # name===version (rare)
    if "===" in line:
        name, version = line.split("===", 1)
        return Package(name=name.strip(), version=version.strip())
    # Unrecognized formats (skip)
    return None


def pip_freeze(python_bin: str) -> List[Package]:
    code, out, err = run_command([python_bin, "-m", "pip", "freeze"])
    if code != 0:
        raise RuntimeError(f"pip freeze failed: {err}")
    packages: List[Package] = []
    for line in out.splitlines():
        pkg = parse_freeze_line(line)
        if pkg:
            packages.append(pkg)
    packages.sort(key=lambda p: p.name.lower())
    return packages


def parse_requirements(req_path: str) -> List[Package]:
    content = read_text_file(req_path)
    packages: List[Package] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-r ") or line.startswith("--"):
            continue
        if " @ " in line:
            name, url = line.split(" @ ", 1)
            packages.append(Package(name=name.strip(), url=url.strip()))
            continue
        if "==" in line:
            name, version = line.split("==", 1)
            packages.append(Package(name=name.strip(), version=version.strip()))
            continue
        if "===" in line:
            name, version = line.split("===", 1)
            packages.append(Package(name=name.strip(), version=version.strip()))
            continue
        # Unpinned entries are ignored to keep determinism
    packages.sort(key=lambda p: p.name.lower())
    return packages


# ------------------------------- Models spec -------------------------------- #


@dataclasses.dataclass
class ModelEntry:
    name: str
    source: Optional[str]
    target_path: str
    checksum: Optional[str]


def sha256_file(path: str) -> Optional[str]:
    try:
        import hashlib

        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return f"sha256:{h.hexdigest()}"
    except FileNotFoundError:
        return None


def load_models_spec(spec_path: str) -> List[Dict[str, object]]:
    path = pathlib.Path(spec_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Models spec not found: {path}")
    text = read_text_file(str(path))
    data: object
    if path.suffix.lower() in {".yml", ".yaml"}:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("PyYAML is required to read YAML specs. Install 'pyyaml' or use JSON.") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    if isinstance(data, dict) and "models" in data:
        raw_models = data["models"]
    elif isinstance(data, list):
        raw_models = data
    else:
        raise ValueError("Models spec must be a list or an object with 'models' list")

    normalized: List[Dict[str, object]] = []
    for idx, m in enumerate(raw_models):
        if not isinstance(m, dict):
            raise ValueError(f"Invalid model entry at index {idx}: {m!r}")
        name = str(m.get("name") or m.get("id") or f"model_{idx}")
        source = m.get("source")
        target_path = m.get("target_path") or m.get("path")
        if not target_path:
            raise ValueError(f"Model '{name}' missing 'target_path'")
        checksum = m.get("checksum")
        normalized.append({
            "name": name,
            "source": source,
            "target_path": str(target_path),
            "checksum": checksum,
        })
    # Sort by name then path to keep stable
    normalized.sort(key=lambda x: (str(x.get("name")).lower(), str(x.get("target_path")).lower()))
    return normalized


def compute_missing_checksums(models: List[Dict[str, object]], env: Dict[str, str]) -> List[ModelEntry]:
    result: List[ModelEntry] = []
    for m in models:
        target_path_raw = str(m["target_path"])  # type: ignore[index]
        target_path = expand_env(target_path_raw, extra_env=env)
        checksum_value = m.get("checksum")
        if not checksum_value:
            checksum_value = sha256_file(target_path)
        result.append(
            ModelEntry(
                name=str(m.get("name")),
                source=(None if m.get("source") is None else str(m.get("source"))),
                target_path=target_path_raw,  # keep raw with env vars for portability
                checksum=(None if checksum_value is None else str(checksum_value)),
            )
        )
    result.sort(key=lambda x: (x.name.lower(), x.target_path.lower()))
    return result


# --------------------------------- CLI ------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Create ComfyUI lock file (beta)")
    p.add_argument("--name", required=True, help="Version name used in lock file name")
    p.add_argument("--comfy-path", dest="comfy_path", default=None, help="Path to local ComfyUI repo (default: $COMFY_HOME/ComfyUI or ./ComfyUI)")
    p.add_argument("--comfy-repo", dest="comfy_repo", default=None, help="Repository URL metadata for ComfyUI (optional)")
    p.add_argument("--venv", dest="venv_path", default=None, help="Path to Python venv used to freeze dependencies (default: $COMFY_HOME/.venv if exists)")
    p.add_argument("--requirements", dest="requirements_path", default=None, help="Requirements file to pin if no venv is provided")
    p.add_argument("--custom-node", dest="custom_node", action="append", default=[], help="Manual custom node: key=value pairs (name=...,path=...,repo=...,commit=...); can be repeated")
    p.add_argument("--models-spec", dest="models_spec", default=None, help="Path to models spec (YAML/JSON). Optional.")
    p.add_argument("--models-dir", dest="models_dir", default=None, help="Base models directory (used only for path expansion; default: $COMFY_HOME/models)")
    p.add_argument("--wheel-url", dest="wheel_urls", action="append", default=[], help="Optional package wheel URL mapping: name=url (repeatable)")
    p.add_argument("--output", dest="output", default=None, help="Explicit output path (overrides default lockfiles/comfy-<name>.lock.json)")
    p.add_argument("--pretty", dest="pretty", action="store_true", help="Pretty-print JSON with indent=2")
    return p


def derive_defaults(args: argparse.Namespace) -> Tuple[str, str, Dict[str, str]]:
    env: Dict[str, str] = {}
    comfy_home = os.environ.get("COMFY_HOME")
    if comfy_home:
        env["COMFY_HOME"] = comfy_home
    else:
        # Default to ./comfy to match init script fallback
        env["COMFY_HOME"] = str((pathlib.Path.cwd() / "comfy").resolve())

    comfy_path = args.comfy_path or str(pathlib.Path(env["COMFY_HOME"]) / "ComfyUI")
    models_dir = args.models_dir or str(pathlib.Path(env["COMFY_HOME"]) / "models")
    return comfy_path, models_dir, env


def choose_python_interpreter(venv_path: Optional[str], env: Dict[str, str]) -> Tuple[str, str]:
    # Prefer venv/bin/python
    if venv_path:
        py = which_python_in_venv(venv_path)
        if py:
            return py, venv_path
    # Try COMFY_HOME/.venv
    default_venv = pathlib.Path(env["COMFY_HOME"]) / ".venv"
    if default_venv.exists():
        py = which_python_in_venv(str(default_venv))
        if py:
            return py, str(default_venv)
    # Fallback to current python
    return sys.executable, ""


def collect_python_section(args: argparse.Namespace, env: Dict[str, str]) -> Dict[str, object]:
    python_bin, used_venv = choose_python_interpreter(args.venv_path, env)

    # Detect python version string
    code, out, _ = run_command([python_bin, "-c", "import platform; print(platform.python_version())"])
    python_version = out if code == 0 else platform.python_version()  # type: ignore[name-defined]

    packages: List[Package] = []
    if args.venv_path or used_venv:
        try:
            packages = pip_freeze(python_bin)
        except Exception:
            packages = []
    if not packages and args.requirements_path:
        packages = parse_requirements(args.requirements_path)

    # Apply optional wheel URL mapping
    wheel_map: Dict[str, str] = {}
    for entry in args.wheel_urls or []:
        if "=" in entry:
            k, v = entry.split("=", 1)
            wheel_map[k.strip()] = v.strip()

    out_packages: List[Dict[str, Optional[str]]] = []
    for p in packages:
        out_packages.append({
            "name": p.name,
            "version": p.version,
            "url": wheel_map.get(p.name, p.url),
        })
    out_packages.sort(key=lambda d: str(d["name"]).lower())

    return {
        "version": python_version,
        "interpreter": python_bin,
        "packages": out_packages,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    comfy_path, models_dir, env = derive_defaults(args)

    # ComfyUI repo info
    comfy_info = collect_repo_info(comfy_path, declared_repo_url=args.comfy_repo)

    # Custom nodes autodiscovery
    auto_nodes = discover_custom_nodes(str(pathlib.Path(comfy_path) / "custom_nodes"))
    manual_entries = parse_kv_list(args.custom_node)
    merged_nodes = merge_custom_nodes(auto_nodes, manual_entries)

    # Python dependencies
    python_section = collect_python_section(args, env)

    # Models
    models_section: List[Dict[str, object]] = []
    if args.models_spec:
        raw_models = load_models_spec(args.models_spec)
        models_with_checksums = compute_missing_checksums(raw_models, env={**env, "MODELS_DIR": models_dir})
        # Convert to plain dicts
        models_section = [dataclasses.asdict(m) for m in models_with_checksums]

    # Convert nodes to serializable form
    custom_nodes_out: List[Dict[str, Optional[str]]] = []
    for n in merged_nodes:
        custom_nodes_out.append({
            "name": n.name,
            "repo": n.repo,
            "commit": n.commit,
            "path": n.path,
        })
    custom_nodes_out.sort(key=lambda d: str(d["name"]).lower())

    data = {
        "schema_version": 1,
        "version_name": args.name,
        "comfyui": {
            "repo": comfy_info.get("repo"),
            "commit": comfy_info.get("commit"),
            "path": comfy_info.get("path"),
        },
        "custom_nodes": custom_nodes_out,
        "python": python_section,
        "models": models_section,
    }

    # Output path
    if args.output:
        output_path = pathlib.Path(args.output)
    else:
        output_path = pathlib.Path("lockfiles") / f"comfy-{args.name}.lock.json"
    safe_makedirs(str(output_path.parent))

    # Stable JSON formatting
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=(2 if args.pretty else None),
            sort_keys=True,
            separators=(",", ":") if not args.pretty else None,
            ensure_ascii=False,
        )

    print(str(output_path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


