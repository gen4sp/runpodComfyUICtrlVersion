#!/usr/bin/env python3
"""
Validate and download models from YAML spec files.

Reads YAML model specifications from models/ directory and:
- Validates YAML structure
- Checks model presence and checksums
- Downloads missing models from sources (hf://, https://, etc.)
- Supports caching and environment variable expansion

Usage:
  python3 scripts/validate_yaml_models.py --models-dir "$COMFY_HOME/models" --cache-dir "$COMFY_HOME/.cache/models"

Or for specific YAML file:
  python3 scripts/validate_yaml_models.py --yaml models/flux-models.yml --models-dir "$COMFY_HOME/models"
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
import time
try:
    # Prefer absolute import for execution as a script from repo root
    from scripts.model_sources import (
        civitai_get_size_bytes,
        civitai_build_download_url_and_headers,
    )
except Exception:
    try:
        # Fallback when executed via "python scripts/validate_yaml_models.py" (sys.path[0] == scripts/)
        from model_sources import (
            civitai_get_size_bytes,  # type: ignore
            civitai_build_download_url_and_headers,  # type: ignore
        )
    except Exception:
        # Last resort: disable civitai support
        civitai_get_size_bytes = None  # type: ignore[assignment]
        civitai_build_download_url_and_headers = None  # type: ignore[assignment]


# ----------------------------- Small utilities ----------------------------- #


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def log_error(msg: str) -> None:
    print(f"[ERROR] {msg}")


def safe_makedirs(path: str) -> None:
    pathlib.Path(path).mkdir(parents=True, exist_ok=True)


def expand_env(path: str, extra_env: Optional[Dict[str, str]] = None) -> str:
    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)
        # Explicitly expand known variables first for determinism/flexibility
        expanded = path.replace("$COMFY_HOME", extra_env.get("COMFY_HOME", ""))
        expanded = expanded.replace("$MODELS_DIR", extra_env.get("MODELS_DIR", ""))
        return os.path.expandvars(expanded)
    return os.path.expandvars(path)


def compute_checksum(path: str, algo: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    h: hashlib._Hash
    algo_lower = algo.lower()
    if algo_lower == "sha256":
        h = hashlib.sha256()
    elif algo_lower == "md5":
        h = hashlib.md5()
    else:
        raise ValueError(f"Unsupported checksum algorithm: {algo}")
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return f"{algo_lower}:{h.hexdigest()}"


def parse_checksum(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not value:
        return None, None
    if ":" in value:
        algo, hexpart = value.split(":", 1)
        return algo.lower().strip(), hexpart.strip().lower()
    # Bare hex means assume sha256 for backwards-compat
    return "sha256", value.strip().lower()


def same_files(src: str, dst: str) -> bool:
    try:
        return os.path.samefile(src, dst)
    except Exception:
        return False


def atomic_copy(src: str, dst: str) -> None:
    safe_makedirs(str(pathlib.Path(dst).parent))
    if same_files(src, dst):
        return
    # Copy to temp then rename
    parent = pathlib.Path(dst).parent
    with tempfile.NamedTemporaryFile(dir=str(parent), delete=False) as tmp:
        tmp_path = tmp.name
    try:
        shutil.copyfile(src, tmp_path)
        os.replace(tmp_path, dst)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def run_command(command: List[str]) -> Tuple[int, str, str]:
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    return proc.returncode, out.strip(), err.strip()


def get_model_size(source: str, timeout: int = 60) -> Optional[int]:
    """Get model size in bytes from source URL or local path."""
    try:
        parsed = urllib.parse.urlparse(source)
        if parsed.scheme in ("http", "https"):
            # Try HEAD request first
            req = urllib.request.Request(source, method="HEAD")
            req.add_header("User-Agent", "runpod-comfy-yaml-verifier/1.0")
            token = os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_length = resp.headers.get("Content-Length")
                if content_length:
                    return int(content_length)
        elif parsed.scheme in ("civitai",):
            if civitai_get_size_bytes:
                size = civitai_get_size_bytes(source, timeout=timeout)
                if isinstance(size, int) and size > 0:
                    return size
        elif parsed.scheme in ("hf", "huggingface"):
            # Build resolve URL and get size
            repo_id, revision, path_in_repo = parse_hf_source(source)
            resolve_url = build_hf_resolve_url(repo_id, revision, path_in_repo)
            return get_model_size(resolve_url, timeout)
        elif parsed.scheme in ("file",):
            path = urllib.request.url2pathname(parsed.path)
            if os.path.exists(path):
                return os.path.getsize(path)
        elif parsed.scheme in ("gs", "gsutil") or source.startswith("gs://"):
            # Use gsutil to get size
            gsutil = shutil.which("gsutil")
            if gsutil:
                code, out, err = run_command([gsutil, "stat", source])
                if code == 0:
                    # Parse gsutil stat output for Content-Length
                    for line in out.split('\n'):
                        if line.startswith('Content-Length:'):
                            return int(line.split(':', 1)[1].strip())
        else:
            # Treat as local filesystem path
            if os.path.exists(source):
                return os.path.getsize(source)
    except Exception as exc:
        log_warn(f"Failed to get size for {source}: {exc}")
    return None


def get_disk_free_space(path: str) -> int:
    """Get free disk space in bytes for the given path.

    - Uses `df -Pk` for consistent, single-line, 1024-block output across platforms.
    - If the path does not exist, walks up to the nearest existing parent to query the correct filesystem.
    - Falls back to shutil.disk_usage/os.statvfs on failure.
    """
    try:
        query_path = path
        try:
            if not os.path.exists(query_path):
                p = pathlib.Path(query_path)
                # Walk up until we find an existing directory; fallback to root
                while not p.exists() and p != p.parent:
                    p = p.parent
                if not p.exists():
                    p = pathlib.Path("/")
                query_path = str(p)
        except Exception:
            # If anything goes wrong determining parent, just fallback to root
            query_path = "/"

        # Prefer POSIX-format, kilobyte blocks to avoid wrapping/locale issues
        code, out, err = run_command(["df", "-Pk", query_path])
        if code == 0 and out:
            lines = [ln for ln in out.splitlines() if ln.strip()]
            # Find a data line (non-header). With -P there should be exactly one
            data_lines = [ln for ln in lines if not ln.lower().startswith("filesystem")]
            line = data_lines[-1] if data_lines else (lines[-1] if len(lines) >= 2 else "")
            if line:
                parts = line.split()
                # parts layout for -P: Filesystem, 1024-blocks, Used, Available, Use%/Capacity, Mounted on
                if len(parts) >= 4:
                    available_kb = int(parts[3])
                    return available_kb * 1024

        # Fallbacks
        log_warn(f"df command failed for {query_path} (orig: {path}), falling back to shutil.disk_usage/statvfs")
        try:
            usage = shutil.disk_usage(query_path)
            return int(usage.free)
        except Exception:
            statvfs = os.statvfs(query_path)
            return statvfs.f_frsize * statvfs.f_bavail
    except Exception as exc:
        log_error(f"Failed to get disk free space for {path}: {exc}")
        return 0


def format_bytes(bytes_value: int) -> str:
    """Format bytes to human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} TB"


# ----------------------------- Cache management ----------------------------- #


# ------------------------ RunPod volume quota helpers ------------------------ #


def _parse_int_env(names: List[str]) -> Optional[int]:
    for name in names:
        val = os.environ.get(name)
        if val:
            try:
                return int(val)
            except Exception:
                try:
                    return int(float(val))
                except Exception:
                    continue
    return None


def get_runpod_quota_bytes() -> Optional[int]:
    """Return declared RunPod volume quota in bytes if provided via env.

    Supported env names (first match wins):
      - RUNPOD_VOLUME_QUOTA_BYTES, RUNPOD_VOLUME_SIZE_BYTES, RUNPOD_VOLUME_BYTES
      - RUNPOD_VOLUME_QUOTA_GB, RUNPOD_VOLUME_SIZE_GB, RUNPOD_VOLUME_GB (GiB)
    """
    # Bytes first
    bytes_val = _parse_int_env([
        "RUNPOD_VOLUME_QUOTA_BYTES",
        "RUNPOD_VOLUME_SIZE_BYTES",
        "RUNPOD_VOLUME_BYTES",
    ])
    if bytes_val is not None and bytes_val > 0:
        return bytes_val

    # Then GB (GiB)
    gb_val = _parse_int_env([
        "RUNPOD_VOLUME_QUOTA_GB",
        "RUNPOD_VOLUME_SIZE_GB",
        "RUNPOD_VOLUME_GB",
    ])
    if gb_val is not None and gb_val > 0:
        return int(gb_val * 1024 * 1024 * 1024)

    # Default 150 GiB if running under a known RunPod-like mount and no envs set
    try:
        root = os.environ.get("RUNPOD_VOLUME_ROOT") or ("/runpod-volume" if os.path.exists("/runpod-volume") else ("/workspace" if os.path.exists("/workspace") else None))
        if root:
            default_gb = _parse_int_env([
                "RUNPOD_VOLUME_DEFAULT_QUOTA_GB",
                "RUNPOD_DEFAULT_QUOTA_GB",
            ])
            if default_gb is None:
                default_gb = 150
            return int(default_gb * 1024 * 1024 * 1024)
    except Exception:
        pass
    return None


def get_runpod_mount_root() -> str:
    env_root = os.environ.get("RUNPOD_VOLUME_ROOT")
    if env_root:
        return env_root
    if os.path.exists("/runpod-volume"):
        return "/runpod-volume"
    if os.path.exists("/workspace"):
        return "/workspace"
    return "/"


def is_under_path(path: str, root: str) -> bool:
    try:
        path_abs = str(pathlib.Path(path).resolve())
        root_abs = str(pathlib.Path(root).resolve())
        return path_abs == root_abs or path_abs.startswith(root_abs.rstrip("/") + "/")
    except Exception:
        return False


def get_directory_disk_usage_bytes(path: str) -> int:
    """Return directory used size in bytes (best-effort, fast path via du -sk)."""
    try:
        code, out, err = run_command(["du", "-sk", path])
        if code == 0 and out:
            first_token = out.strip().split()[0]
            used_kb = int(first_token)
            return used_kb * 1024
    except Exception:
        pass
    # Fallback: python walk (may be slow on large trees)
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                try:
                    total += os.path.getsize(fpath)
                except Exception:
                    continue
    except Exception:
        pass
    return total


def get_effective_free_space(path: str) -> int:
    """Return free space in bytes for a path, considering RunPod quotas if provided.

    If the path resides under RUNPOD volume root and quota env is set, compute:
        free = max(0, quota_bytes - used_bytes(runpod_root))
    Otherwise, fallback to get_disk_free_space(path).
    """
    try:
        runpod_root = get_runpod_mount_root()
        quota_bytes = get_runpod_quota_bytes()
        if quota_bytes and is_under_path(path, runpod_root):
            # Use DU on the root of volume to reflect user's allocated usage
            used_bytes = get_directory_disk_usage_bytes(runpod_root)
            free_bytes = quota_bytes - used_bytes
            if free_bytes < 0:
                free_bytes = 0
            return free_bytes
    except Exception:
        # Fall back if anything goes wrong
        pass
    return get_disk_free_space(path)


def _log_enospc_context(name: str, source: object, target_path: str, cache_dir: str, tmp_path: Optional[str]) -> None:
    """Print contextual info for ENOSPC: sizes and free space per relevant dirs."""
    try:
        # Estimate size
        size_bytes = None
        try:
            size_bytes = get_model_size(str(source), timeout=30) if isinstance(source, str) else None
        except Exception:
            size_bytes = None

        target_dir = str(pathlib.Path(target_path).parent)
        free_target = get_effective_free_space(target_dir)
        free_cache = get_effective_free_space(cache_dir)
        tmp_dir = str(pathlib.Path(tmp_path).parent) if tmp_path else cache_dir
        free_tmp = get_effective_free_space(tmp_dir)

        log_error("Недостаточно места на диске (ENOSPC):")
        log_error(f"  Модель: {name}")
        if size_bytes is not None:
            log_error(f"  Размер артефакта: {format_bytes(size_bytes)}")
        else:
            log_error("  Размер артефакта: неизвестен")
        log_error(f"  Свободно в каталоге назначения ({target_dir}): {format_bytes(free_target)}")
        log_error(f"  Свободно в кэше ({cache_dir}): {format_bytes(free_cache)}")
        log_error(f"  Свободно во временном каталоге ({tmp_dir}): {format_bytes(free_tmp)}")
    except Exception as exc:
        log_warn(f"Не удалось вывести контекст ENOSPC: {exc}")


def cache_key_path(cache_dir: str, checksum_value: Optional[str], fallback_name: str) -> Tuple[str, str]:
    """Return (dir, path) for a cache entry.

    If checksum is known (algo:hex), use `<cache>/<algo>/<hex>`.
    Otherwise, use `<cache>/by-name/<fallback_name>`.
    """
    if checksum_value:
        algo, hexpart = parse_checksum(checksum_value)
        if algo and hexpart:
            entry_dir = pathlib.Path(cache_dir) / algo / hexpart[:2] / hexpart
            return str(entry_dir), str(entry_dir / "blob")
    entry_dir = pathlib.Path(cache_dir) / "by-name" / fallback_name
    return str(entry_dir), str(entry_dir / "blob")


def store_in_cache(cache_path: str, src_path: str) -> None:
    safe_makedirs(str(pathlib.Path(cache_path).parent))
    if os.path.exists(cache_path):
        return
    # Use atomic copy
    atomic_copy(src_path, cache_path)


# ------------------------------- Downloaders -------------------------------- #


def download_http(url: str, dest_path: str, timeout: int = 60, headers: Optional[Dict[str, str]] = None, show_progress: bool = True) -> None:
    req_headers = {"User-Agent": "runpod-comfy-yaml-verifier/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - user-controlled URLs expected
        total = resp.length if getattr(resp, "length", None) is not None else None
        if total is None:
            # Try header
            total_hdr = resp.headers.get("Content-Length")
            total = int(total_hdr) if total_hdr else None
        safe_makedirs(str(pathlib.Path(dest_path).parent))
        chunk = 1024 * 1024
        downloaded = 0
        last_print = 0.0
        start_ts = time.time()
        with open(dest_path, "wb") as f:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                downloaded += len(buf)
                now = time.time()
                if show_progress and (now - last_print) >= 0.5:
                    last_print = now
                    if total and total > 0:
                        pct = downloaded / total
                        elapsed = now - start_ts
                        speed = downloaded / max(elapsed, 1e-6)
                        remaining = (total - downloaded) / max(speed, 1e-6)
                        log_info(f"  ↓ {format_bytes(downloaded)} / {format_bytes(total)} ({pct*100:.1f}%), {format_bytes(int(speed))}/s, ETA {int(remaining)}s")
                    else:
                        log_info(f"  ↓ {format_bytes(downloaded)} / ?")


def download_file(src_path: str, dest_path: str) -> None:
    # src_path may be file:///path or plain filesystem path
    parsed = urllib.parse.urlparse(src_path)
    if parsed.scheme == "file":
        path = urllib.request.url2pathname(parsed.path)
    else:
        path = src_path
    if not os.path.exists(path):
        raise FileNotFoundError(f"Source file not found: {path}")
    safe_makedirs(str(pathlib.Path(dest_path).parent))
    shutil.copyfile(path, dest_path)


def download_gs(url: str, dest_path: str) -> None:
    # Prefer gsutil if available (avoids extra python deps)
    gsutil = shutil.which("gsutil")
    if not gsutil:
        raise RuntimeError("gsutil is required to fetch gs:// URLs; please install Google Cloud SDK or provide http(s)/file source")
    safe_makedirs(str(pathlib.Path(dest_path).parent))
    code, _, err = run_command([gsutil, "-q", "cp", url, dest_path])
    if code != 0:
        raise RuntimeError(f"gsutil cp failed: {err}")


def build_hf_resolve_url(repo_id: str, revision: str, path_in_repo: str) -> str:
    repo_id_quoted = "/".join(urllib.parse.quote(part, safe="") for part in repo_id.split("/"))
    path_quoted = urllib.parse.quote(path_in_repo.lstrip("/"), safe="/")
    rev_quoted = urllib.parse.quote(revision, safe="")
    return f"https://huggingface.co/{repo_id_quoted}/resolve/{rev_quoted}/{path_quoted}?download=true"


def parse_hf_source(source: str) -> Tuple[str, str, str]:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme not in ("hf", "huggingface"):
        raise ValueError("not an hf url")
    org = parsed.netloc
    path = parsed.path.lstrip("/")
    if not org or not path:
        raise ValueError("Invalid hf url. Expected hf://<org>/<repo>/<file>[?rev=...] or hf://<org>/<repo>@<rev>/<file>")
    segments = path.split("/")
    repo_segment = segments[0]
    path_segments = segments[1:]
    if not path_segments:
        raise ValueError("hf url must include a file path inside repo")
    revision: Optional[str] = None
    if "@" in repo_segment:
        repo_name, revision = repo_segment.split("@", 1)
    else:
        repo_name = repo_segment
    qs = urllib.parse.parse_qs(parsed.query)
    if not revision:
        rev_list = qs.get("rev") or qs.get("revision")
        revision = rev_list[0] if rev_list else "main"
    repo_id = f"{org}/{repo_name}"
    path_in_repo = "/".join(path_segments)
    return repo_id, revision, path_in_repo


def download_hf(source: str, dest_path: str, timeout: int = 60) -> None:
    repo_id, revision, path_in_repo = parse_hf_source(source)
    resolve_url = build_hf_resolve_url(repo_id, revision, path_in_repo)
    token = os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    download_http(resolve_url, dest_path, timeout=timeout, headers=headers)


def fetch_to_temp(source: str, tmp_dir: str, timeout: int = 60) -> str:
    parsed = urllib.parse.urlparse(source)
    filename = pathlib.Path(parsed.path or "artifact").name or "artifact"
    with tempfile.NamedTemporaryFile(dir=tmp_dir, delete=False, prefix=f"dl_{filename}.") as tmp:
        tmp_path = tmp.name
    try:
        if parsed.scheme in ("http", "https"):
            download_http(source, tmp_path, timeout=timeout)
        elif parsed.scheme in ("file",):
            download_file(source, tmp_path)
        elif parsed.scheme in ("gs", "gsutil") or source.startswith("gs://"):
            download_gs(source, tmp_path)
        elif parsed.scheme in ("hf", "huggingface"):
            download_hf(source, tmp_path, timeout=timeout)
        elif parsed.scheme in ("civitai",):
            if not civitai_build_download_url_and_headers:
                raise RuntimeError("civitai support is unavailable in this environment")
            url, headers = civitai_build_download_url_and_headers(source)
            download_http(url, tmp_path, timeout=timeout, headers=headers)
        else:
            # Treat as local filesystem path
            download_file(source, tmp_path)
        return tmp_path
    except Exception:
        # Ensure temp gets removed on error
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


# --------------------------------- Core ------------------------------------- #


@dataclasses.dataclass
class VerifyResult:
    yaml_file: str
    name: str
    target_path: str
    status: str  # ok|downloaded|updated|error
    message: str = ""


def load_yaml_models(yaml_path: str) -> List[Dict[str, object]]:
    """Load models from YAML file similar to create_version.py logic."""
    try:
        import yaml  # type: ignore
    except Exception as exc:
        raise RuntimeError("PyYAML is required to read YAML files. Install 'pyyaml'") from exc

    path = pathlib.Path(yaml_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if isinstance(data, dict) and "models" in data:
        raw_models = data["models"]
    elif isinstance(data, list):
        raw_models = data
    else:
        raise ValueError(f"YAML file {yaml_path} must contain 'models' list or be a list")

    if not isinstance(raw_models, list):
        raise ValueError(f"'models' section in {yaml_path} must be a list")

    # Normalize fields to str/Optional[str]
    normalized: List[Dict[str, object]] = []
    for m in raw_models:
        if not isinstance(m, dict):
            continue
        normalized.append({
            "name": str(m.get("name") or m.get("id") or "model"),
            "source": (None if m.get("source") is None else str(m.get("source"))),
            "target_path": str(m.get("target_path") or m.get("path") or ""),
            "checksum": (None if m.get("checksum") is None else str(m.get("checksum"))),
        })
    return normalized


def validate_yaml_structure(yaml_path: str) -> List[str]:
    """Validate YAML file structure and return list of validation errors."""
    errors = []

    try:
        models = load_yaml_models(yaml_path)
    except Exception as e:
        return [f"Failed to load YAML: {e}"]

    if not models:
        errors.append("No models found in YAML file")
        return errors

    for i, model in enumerate(models):
        name = model.get("name", "")
        source = model.get("source")
        target_path = model.get("target_path", "")
        checksum = model.get("checksum")

        if not name:
            errors.append(f"Model {i}: missing 'name' field")

        if not target_path:
            errors.append(f"Model '{name}': missing 'target_path' field")

        # Check if source is provided when checksum is present
        if checksum and not source:
            errors.append(f"Model '{name}': checksum provided but no source for verification")

        # Basic URL validation for source
        if source:
            parsed = urllib.parse.urlparse(source)
            if not parsed.scheme and not os.path.exists(source):
                errors.append(f"Model '{name}': source '{source}' is not a valid URL or local path")

    return errors


def derive_env(models_dir: Optional[str]) -> Dict[str, str]:
    env: Dict[str, str] = {}
    comfy_home = os.environ.get("COMFY_HOME")
    if comfy_home:
        env["COMFY_HOME"] = comfy_home
    else:
        env["COMFY_HOME"] = str((pathlib.Path.cwd() / "comfy").resolve())

    models_dir_env = os.environ.get("MODELS_DIR")
    env["MODELS_DIR"] = models_dir or models_dir_env or str(pathlib.Path(env["COMFY_HOME"]) / "models")
    return env


def verify_single_model(yaml_file: str, model: Dict[str, object], env: Dict[str, str], cache_dir: str, overwrite: bool, timeout: int) -> VerifyResult:
    name = str(model.get("name"))
    target_path_raw = str(model.get("target_path"))
    if not target_path_raw:
        return VerifyResult(yaml_file=yaml_file, name=name, target_path="", status="error", message="missing target_path")

    target_path = expand_env(target_path_raw, extra_env=env)
    expected_algo, expected_hex = parse_checksum(model.get("checksum") if isinstance(model.get("checksum"), str) else None)
    expected_checksum = f"{expected_algo}:{expected_hex}" if expected_algo and expected_hex else None
    source = (None if model.get("source") in (None, "") else str(model.get("source")))

    # Quick OK path: file exists and checksum matches (if provided)
    if os.path.exists(target_path):
        if expected_algo and expected_hex:
            actual = compute_checksum(target_path, algo=expected_algo)
            if actual.split(":", 1)[1] == expected_hex:
                # Populate cache if missing
                cache_entry_dir, cache_entry_path = cache_key_path(cache_dir, expected_checksum, pathlib.Path(target_path).name)
                if not os.path.exists(cache_entry_path):
                    try:
                        store_in_cache(cache_entry_path, target_path)
                    except Exception as exc:
                        log_warn(f"cache store failed for {name}: {exc}")
                return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="ok", message="present")
            else:
                if not source:
                    return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="error", message="checksum mismatch and no source to refetch")
                if not overwrite:
                    return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="error", message="checksum mismatch; use --overwrite to replace from source")
                # Fall through to re-fetch
        else:
            # No expected checksum: consider present
            # Also add to cache keyed by derived sha256
            try:
                actual_sha = compute_checksum(target_path, algo="sha256")
                _, cache_entry_path = cache_key_path(cache_dir, actual_sha, pathlib.Path(target_path).name)
                if not os.path.exists(cache_entry_path):
                    store_in_cache(cache_entry_path, target_path)
            except Exception:
                pass
            return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="ok", message="present (no checksum)")

    # At this point: file missing OR mismatch with overwrite allowed
    if not source:
        return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="error", message="missing and no source provided")

    # Try cache when checksum known
    if expected_checksum:
        cache_entry_dir, cache_entry_path = cache_key_path(cache_dir, expected_checksum, pathlib.Path(target_path).name)
        if os.path.exists(cache_entry_path):
            try:
                atomic_copy(cache_entry_path, target_path)
                return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="downloaded", message="restored from cache")
            except Exception as exc:
                log_warn(f"failed to restore from cache for {name}: {exc}")

    # Preflight: ensure enough space for this model (if size known)
    pre_size: Optional[int] = None
    try:
        pre_size = get_model_size(str(source), timeout=min(timeout, 60)) if isinstance(source, str) else None
    except Exception:
        pre_size = None
    if pre_size and pre_size > 0:
        target_dir = str(pathlib.Path(target_path).parent)
        free_target = get_effective_free_space(target_dir)
        free_cache = get_effective_free_space(cache_dir)
        required = pre_size
        available = min(free_target, free_cache)
        if required > available:
            try:
                _log_enospc_context(name=name, source=source, target_path=target_path, cache_dir=cache_dir, tmp_path=None)
            except Exception:
                pass
            shortage = required - available
            return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="error", message=f"not enough space (short by {format_bytes(shortage)})")

    # Remember previous existence to report status accurately
    previously_exists = os.path.exists(target_path)

    # Fetch from source to temp in cache directory (same mount, avoid /tmp)
    tmp_dir = tempfile.mkdtemp(prefix="validate_yaml_", dir=cache_dir)
    try:
        try:
            tmp_download = fetch_to_temp(source, tmp_dir=tmp_dir, timeout=timeout)
        except OSError as exc:
            if getattr(exc, "errno", None) == 28:
                # No space left when downloading to temp/cache area
                try:
                    _log_enospc_context(name=name, source=source, target_path=target_path, cache_dir=cache_dir, tmp_path=None)
                except Exception:
                    pass
                return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="error", message="no space left on device (downloading)")
            raise
        # Validate checksum if expected
        if expected_algo and expected_hex:
            actual = compute_checksum(tmp_download, algo=expected_algo)
            if actual.split(":", 1)[1] != expected_hex:
                return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="error", message="downloaded checksum mismatch")
        else:
            # Derive sha256 for caching
            try:
                derived_sha = compute_checksum(tmp_download, algo="sha256")
            except Exception:
                derived_sha = None  # type: ignore[assignment]
            if derived_sha:
                expected_checksum = derived_sha

        # Store to cache and copy to target
        _, cache_entry_path = cache_key_path(cache_dir, expected_checksum, pathlib.Path(target_path).name)
        try:
            store_in_cache(cache_entry_path, tmp_download)
        except OSError as exc:
            if getattr(exc, "errno", None) == 28:
                try:
                    _log_enospc_context(name=name, source=source, target_path=target_path, cache_dir=cache_dir, tmp_path=tmp_download)
                except Exception:
                    pass
                return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="error", message="no space left on device (caching)")
            else:
                log_warn(f"cache store failed for {name}: {exc}")

        try:
            atomic_copy(cache_entry_path if os.path.exists(cache_entry_path) else tmp_download, target_path)
        except OSError as exc:
            if getattr(exc, "errno", None) == 28:
                try:
                    _log_enospc_context(name=name, source=source, target_path=target_path, cache_dir=cache_dir, tmp_path=tmp_download)
                except Exception:
                    pass
                return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status="error", message="no space left on device (final copy)")
            raise
        return VerifyResult(yaml_file=yaml_file, name=name, target_path=target_path, status=("updated" if previously_exists else "downloaded"), message="fetched from source")
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def check_disk_space(yaml_files: List[str], models_dir: Optional[str], cache_dir: Optional[str], timeout: int, verbose: bool) -> bool:
    """Check if there's enough disk space for all models to be downloaded."""
    env = derive_env(models_dir=models_dir)

    # Default cache dir
    if cache_dir:
        resolved_cache_dir = cache_dir
    else:
        comfy_home = env["COMFY_HOME"]
        resolved_cache_dir = str(pathlib.Path(comfy_home) / ".cache" / "models")

    # Ensure directories exist so that disk space is checked on the correct mount point
    try:
        safe_makedirs(env["MODELS_DIR"])
    except Exception:
        pass
    try:
        safe_makedirs(resolved_cache_dir)
    except Exception:
        pass

    # Collect all models that need to be downloaded
    models_to_check = []
    total_size = 0
    unknown_sizes = []

    for yaml_file in yaml_files:
        try:
            models = load_yaml_models(yaml_file)
        except Exception:
            continue

        for model in models:
            name = str(model.get("name", ""))
            target_path_raw = str(model.get("target_path", ""))
            if not target_path_raw:
                continue

            target_path = expand_env(target_path_raw, extra_env=env)
            source = model.get("source")

            # Skip if file already exists
            if os.path.exists(target_path):
                continue

            # Skip if no source provided
            if not source:
                continue

            models_to_check.append((name, source, target_path))
            size = get_model_size(str(source), timeout=timeout)
            if size is not None:
                total_size += size
            else:
                unknown_sizes.append(name)

    if not models_to_check:
        log_info("Все модели уже присутствуют, проверка места на диске не требуется")
        return True

    # Check disk space for models directory and cache directory using effective (quota-aware) values
    models_disk_free = get_effective_free_space(env["MODELS_DIR"])
    cache_disk_free = get_effective_free_space(resolved_cache_dir)

    # Use the minimum free space (both locations must have enough for temp + final)
    available_space = min(models_disk_free, cache_disk_free)

    log_info("Проверка места на диске:")
    log_info(f"  Моделей к загрузке: {len(models_to_check)}")
    log_info(f"  Общий размер моделей: {format_bytes(total_size)}")
    log_info(f"  Свободно в MODELS_DIR ({env['MODELS_DIR']}): {format_bytes(models_disk_free)}")
    log_info(f"  Свободно в CACHE ({resolved_cache_dir}): {format_bytes(cache_disk_free)}")
    log_info(f"  Будет использовано минимальное доступное: {format_bytes(available_space)}")

    if unknown_sizes:
        log_warn(f"Размер неизвестен для моделей: {', '.join(unknown_sizes)}")

    if total_size > available_space:
        shortage = total_size - available_space
        log_error(f"Недостаточно места на диске! Не хватает: {format_bytes(shortage)}")
        return False
    else:
        remaining = available_space - total_size
        log_info(f"Место достаточно. После установки останется: {format_bytes(remaining)}")
        return True


def run_validation(yaml_files: List[str], models_dir: Optional[str], cache_dir: Optional[str], overwrite: bool, timeout: int, verbose: bool, validate_only: bool, skip_disk_check: bool, workers: int) -> int:
    env = derive_env(models_dir=models_dir)

    # Default cache dir
    if cache_dir:
        resolved_cache_dir = cache_dir
    else:
        comfy_home = env["COMFY_HOME"]
        resolved_cache_dir = str(pathlib.Path(comfy_home) / ".cache" / "models")
    safe_makedirs(resolved_cache_dir)

    # Check disk space analysis (always, unless explicitly skipped)
    if not skip_disk_check:
        disk_check_passed = check_disk_space(yaml_files, models_dir, cache_dir, timeout, verbose)
        if not validate_only and not disk_check_passed:
            log_error("Проверка места на диске не пройдена. Остановка выполнения.")
            return 1

    all_results: List[VerifyResult] = []

    # Validate YAMLs and collect models
    models_to_process: List[Tuple[str, Dict[str, object]]] = []
    for yaml_file in yaml_files:
        validation_errors = validate_yaml_structure(yaml_file)
        if validation_errors:
            for error in validation_errors:
                log_error(f"{yaml_file}: {error}")
            if validate_only:
                all_results.append(VerifyResult(yaml_file=yaml_file, name="", target_path="", status="error", message="validation failed"))
                continue
        try:
            models = load_yaml_models(yaml_file)
        except Exception as exc:
            log_error(f"Failed to load models from {yaml_file}: {exc}")
            all_results.append(VerifyResult(yaml_file=yaml_file, name="", target_path="", status="error", message=str(exc)))
            continue
        if not models:
            log_warn(f"No models found in {yaml_file}")
            continue
        for m in models:
            models_to_process.append((yaml_file, m))

    if validate_only:
        # Only structure validation
        total = len(yaml_files)
        errors = sum(1 for r in all_results if r.status == "error")
        log_info(f"Validation summary: total={total}, errors={errors}")
        return 0 if errors == 0 else 1

    # Parallel verification/download
    workers = max(1, int(workers))
    if workers == 1:
        for yaml_file, m in models_to_process:
            try:
                res = verify_single_model(yaml_file, m, env=env, cache_dir=resolved_cache_dir, overwrite=overwrite, timeout=timeout)
                all_results.append(res)
                if verbose:
                    log_info(f"{yaml_file} - {res.name}: {res.status} - {res.message}")
            except Exception as exc:
                target = str(m.get("target_path")) if isinstance(m.get("target_path"), str) else ""
                all_results.append(VerifyResult(yaml_file=yaml_file, name=str(m.get("name")), target_path=target, status="error", message=str(exc)))
                log_error(f"{yaml_file} - {m.get('name')}: error - {exc}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_meta = {}
            for yaml_file, m in models_to_process:
                future = executor.submit(verify_single_model, yaml_file, m, env, resolved_cache_dir, overwrite, timeout)
                future_to_meta[future] = (yaml_file, m)
            for future in as_completed(future_to_meta):
                yaml_file, m = future_to_meta[future]
                try:
                    res = future.result()
                    all_results.append(res)
                    if verbose:
                        log_info(f"{yaml_file} - {res.name}: {res.status} - {res.message}")
                except Exception as exc:
                    target = str(m.get("target_path")) if isinstance(m.get("target_path"), str) else ""
                    all_results.append(VerifyResult(yaml_file=yaml_file, name=str(m.get("name")), target_path=target, status="error", message=str(exc)))
                    log_error(f"{yaml_file} - {m.get('name')}: error - {exc}")

    if validate_only:
        # Only structure validation
        total = len(yaml_files)
        errors = sum(1 for r in all_results if r.status == "error")
        log_info(f"Validation summary: total={total}, errors={errors}")
        return 0 if errors == 0 else 1

    # Download/verification results
    total = len(all_results)
    ok = sum(1 for r in all_results if r.status == "ok")
    downloaded = sum(1 for r in all_results if r.status in ("downloaded", "updated"))
    errors = sum(1 for r in all_results if r.status == "error")

    log_info(f"Summary: total={total}, ok={ok}, fetched={downloaded}, errors={errors}")
    return 0 if errors == 0 else 1


# --------------------------------- CLI ------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Validate and download models from YAML spec files")
    p.add_argument("--yaml", nargs="+", help="Path to specific YAML file(s) to process. If not provided, processes all .yml/.yaml files in models/ directory")
    p.add_argument("--models-dir", default=None, help="Base models directory for $MODELS_DIR expansion (default: $COMFY_HOME/models)")
    p.add_argument("--cache-dir", default=None, help="Cache directory for downloaded artifacts (default: $COMFY_HOME/.cache/models)")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing files if checksum mismatch and source is available")
    p.add_argument("--timeout", type=int, default=120, help="Network timeout in seconds for http(s)/gs downloads")
    p.add_argument("--verbose", action="store_true", help="Verbose output (per-model status)")
    p.add_argument("--validate-only", action="store_true", help="Only validate YAML structure, don't download models")
    p.add_argument("--skip-disk-check", action="store_true", help="Skip disk space check before downloading models")
    p.add_argument("--workers", type=int, default=4, help="Number of parallel download workers (default: 4). Use 1 for sequential")
    return p


def find_yaml_files() -> List[str]:
    """Find all YAML files in models/ directory."""
    models_dir = pathlib.Path("models")
    if not models_dir.exists():
        return []

    yaml_files = []
    for ext in ["*.yml", "*.yaml"]:
        yaml_files.extend(str(p) for p in models_dir.glob(ext))

    return sorted(yaml_files)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Determine which YAML files to process
    if args.yaml:
        yaml_files = args.yaml
    else:
        yaml_files = find_yaml_files()
        if not yaml_files:
            log_error("No YAML files found in models/ directory. Use --yaml to specify file paths.")
            return 1

    log_info(f"Processing {len(yaml_files)} YAML file(s): {', '.join(yaml_files)}")

    try:
        return run_validation(
            yaml_files=yaml_files,
            models_dir=args.models_dir,
            cache_dir=args.cache_dir,
            overwrite=args.overwrite,
            timeout=args.timeout,
            verbose=args.verbose,
            validate_only=args.validate_only,
            skip_disk_check=args.skip_disk_check,
            workers=args.workers,
        )
    except FileNotFoundError as exc:
        log_error(str(exc))
        return 1
    except Exception as exc:
        log_error(f"unexpected error: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
