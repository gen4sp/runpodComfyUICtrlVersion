#!/usr/bin/env python3
"""
Verify and fetch model artifacts declared in a ComfyUI lock file.

Features:
- Expands env vars in target paths (supports $COMFY_HOME and $MODELS_DIR)
- Checks file presence and checksum (sha256 preferred; md5 supported)
- Downloads missing artifacts from `source` (http(s), file path, gs:// via gsutil)
- Caches downloads by checksum to avoid re-downloading

Usage example:
  python3 scripts/verify_models.py \
    --lock lockfiles/comfy-<name>.lock.json \
    --models-dir "$COMFY_HOME/models" \
    --cache-dir "$COMFY_HOME/.cache/models" [--cache]

Exit codes:
  0: all models present and valid (or successfully downloaded)
  1: one or more models missing or invalid and couldn't be fixed
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List, Optional, Tuple


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


# ----------------------------- Cache management ----------------------------- #


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


def download_http(url: str, dest_path: str, timeout: int = 60, headers: Optional[Dict[str, str]] = None) -> None:
    req_headers = {"User-Agent": "runpod-comfy-verifier/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - user-controlled URLs expected
        safe_makedirs(str(pathlib.Path(dest_path).parent))
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(resp, f, length=1024 * 1024)


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


def parse_civitai_source(source: str) -> str:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme not in ("civitai",):
        raise ValueError("not a civitai url")
    path = parsed.path.lstrip("/")
    if not path:
        raise ValueError("Invalid civitai url. Expected civitai://models/<id> or civitai://api/download/models/<id>")
    return path


def build_civitai_url(path: str) -> str:
    if path.startswith("api/download/models/"):
        return f"https://civitai.com/{path}"
    elif path.startswith("models/"):
        model_id = path.split("/")[-1]
        return f"https://civitai.com/api/download/models/{model_id}"
    else:
        raise ValueError("Unsupported civitai path format")


def download_civitai(source: str, dest_path: str, timeout: int = 60) -> None:
    path = parse_civitai_source(source)
    download_url = build_civitai_url(path)
    token = os.environ.get("CIVITAI_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    download_http(download_url, dest_path, timeout=timeout, headers=headers)


def download_hf(source: str, dest_path: str, timeout: int = 60) -> None:
    repo_id, revision, path_in_repo = parse_hf_source(source)
    resolve_url = build_hf_resolve_url(repo_id, revision, path_in_repo)
    token = os.environ.get("HF_TOKEN")
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
            download_civitai(source, tmp_path, timeout=timeout)
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
    name: str
    target_path: str
    status: str  # ok|downloaded|updated|error
    message: str = ""


def load_lock_models(lock_path: str) -> List[Dict[str, object]]:
    with open(lock_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    models = data.get("models", [])
    if not isinstance(models, list):
        raise ValueError("Invalid lock file format: 'models' must be a list")
    # Normalize fields to str/Optional[str]
    normalized: List[Dict[str, object]] = []
    for m in models:
        if not isinstance(m, dict):
            continue
        normalized.append({
            "name": str(m.get("name") or m.get("id") or "model"),
            "source": (None if m.get("source") is None else str(m.get("source"))),
            "target_path": str(m.get("target_path") or m.get("path") or ""),
            "checksum": (None if m.get("checksum") is None else str(m.get("checksum"))),
        })
    return normalized


def derive_env(models_dir: Optional[str]) -> Dict[str, str]:
    env: Dict[str, str] = {}
    comfy_home = os.environ.get("COMFY_HOME")
    if comfy_home:
        env["COMFY_HOME"] = comfy_home
    else:
        env["COMFY_HOME"] = str((pathlib.Path.cwd() / "comfy").resolve())
    env["MODELS_DIR"] = models_dir or str(pathlib.Path(env["COMFY_HOME"]) / "models")
    return env


def verify_single_model(model: Dict[str, object], env: Dict[str, str], cache_dir: str, overwrite: bool, timeout: int, no_cache: bool) -> VerifyResult:
    name = str(model.get("name"))
    target_path_raw = str(model.get("target_path"))
    if not target_path_raw:
        return VerifyResult(name=name, target_path="", status="error", message="missing target_path")

    target_path = expand_env(target_path_raw, extra_env=env)
    expected_algo, expected_hex = parse_checksum(model.get("checksum") if isinstance(model.get("checksum"), str) else None)
    expected_checksum = f"{expected_algo}:{expected_hex}" if expected_algo and expected_hex else None
    source = (None if model.get("source") in (None, "") else str(model.get("source")))

    # Quick OK path: file exists and checksum matches (if provided)
    if os.path.exists(target_path):
        if expected_algo and expected_hex:
            actual = compute_checksum(target_path, algo=expected_algo)
            if actual.split(":", 1)[1] == expected_hex:
                # Populate cache if missing (unless disabled)
                if not no_cache and cache_dir:
                    cache_entry_dir, cache_entry_path = cache_key_path(cache_dir, expected_checksum, pathlib.Path(target_path).name)
                    if not os.path.exists(cache_entry_path):
                        try:
                            store_in_cache(cache_entry_path, target_path)
                        except Exception as exc:
                            log_warn(f"cache store failed for {name}: {exc}")
                return VerifyResult(name=name, target_path=target_path, status="ok", message="present")
            else:
                if not source:
                    return VerifyResult(name=name, target_path=target_path, status="error", message="checksum mismatch and no source to refetch")
                if not overwrite:
                    return VerifyResult(name=name, target_path=target_path, status="error", message="checksum mismatch; use --overwrite to replace from source")
                # Fall through to re-fetch
        else:
            # No expected checksum: consider present
            # Also add to cache keyed by derived sha256
            if not no_cache and cache_dir:
                try:
                    actual_sha = compute_checksum(target_path, algo="sha256")
                    _, cache_entry_path = cache_key_path(cache_dir, actual_sha, pathlib.Path(target_path).name)
                    if not os.path.exists(cache_entry_path):
                        store_in_cache(cache_entry_path, target_path)
                except Exception:
                    pass
            return VerifyResult(name=name, target_path=target_path, status="ok", message="present (no checksum)")

    # At this point: file missing OR mismatch with overwrite allowed
    if not source:
        return VerifyResult(name=name, target_path=target_path, status="error", message="missing and no source provided")

    # Try cache when checksum known (unless disabled)
    if not no_cache and expected_checksum and cache_dir:
        cache_entry_dir, cache_entry_path = cache_key_path(cache_dir, expected_checksum, pathlib.Path(target_path).name)
        if os.path.exists(cache_entry_path):
            try:
                atomic_copy(cache_entry_path, target_path)
                return VerifyResult(name=name, target_path=target_path, status="downloaded", message="restored from cache")
            except Exception as exc:
                log_warn(f"failed to restore from cache for {name}: {exc}")

    # Fetch from source to temp (prefer cache dir when enabled to stay on same mount)
    if not no_cache and cache_dir:
        tmp_parent = cache_dir
    else:
        tmp_parent = str(pathlib.Path(target_path).parent)
    tmp_dir = tempfile.mkdtemp(prefix="verify_models_", dir=tmp_parent)
    try:
        tmp_download = fetch_to_temp(source, tmp_dir=tmp_dir, timeout=timeout)
        # Validate checksum if expected
        if expected_algo and expected_hex:
            actual = compute_checksum(tmp_download, algo=expected_algo)
            if actual.split(":", 1)[1] != expected_hex:
                return VerifyResult(name=name, target_path=target_path, status="error", message="downloaded checksum mismatch")
        else:
            # Derive sha256 for caching
            try:
                derived_sha = compute_checksum(tmp_download, algo="sha256")
            except Exception:
                derived_sha = None  # type: ignore[assignment]
            if derived_sha:
                expected_checksum = derived_sha

        # Store to cache (if enabled) and copy to target
        if not no_cache and cache_dir:
            _, cache_entry_path = cache_key_path(cache_dir, expected_checksum, pathlib.Path(target_path).name)
            try:
                store_in_cache(cache_entry_path, tmp_download)
            except Exception as exc:
                log_warn(f"cache store failed for {name}: {exc}")
            src_path = cache_entry_path if os.path.exists(cache_entry_path) else tmp_download
        else:
            src_path = tmp_download

        atomic_copy(src_path, target_path)
        return VerifyResult(name=name, target_path=target_path, status=("updated" if os.path.exists(target_path) else "downloaded"), message="fetched from source")
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def run_verification(lock_path: str, models_dir: Optional[str], cache_dir: Optional[str], overwrite: bool, timeout: int, verbose: bool, use_cache: bool) -> int:
    env = derive_env(models_dir=models_dir)
    models = load_lock_models(lock_path)
    if not models:
        log_info("No models section in lock file; nothing to verify")
        return 0

    # Default cache dir (enabled only when use_cache)
    if not use_cache:
        resolved_cache_dir = None
    else:
        if cache_dir:
            resolved_cache_dir = cache_dir
        else:
            comfy_home = env["COMFY_HOME"]
            resolved_cache_dir = str(pathlib.Path(comfy_home) / ".cache" / "models")
        safe_makedirs(resolved_cache_dir)

    results: List[VerifyResult] = []
    for m in models:
        try:
            res = verify_single_model(m, env=env, cache_dir=(resolved_cache_dir or ""), overwrite=overwrite, timeout=timeout, no_cache=(not use_cache))
            results.append(res)
            if verbose:
                log_info(f"{res.name}: {res.status} - {res.message}")
        except Exception as exc:
            target = str(m.get("target_path")) if isinstance(m.get("target_path"), str) else ""
            results.append(VerifyResult(name=str(m.get("name")), target_path=target, status="error", message=str(exc)))
            log_error(f"{m.get('name')}: error - {exc}")

    total = len(results)
    ok = sum(1 for r in results if r.status == "ok")
    downloaded = sum(1 for r in results if r.status in ("downloaded", "updated"))
    errors = sum(1 for r in results if r.status == "error")

    log_info(f"Summary: total={total}, ok={ok}, fetched={downloaded}, errors={errors}")
    return 0 if errors == 0 else 1


# --------------------------------- CLI ------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verify and download models from lock file")
    p.add_argument("--lock", required=True, help="Path to lock file (JSON)")
    p.add_argument("--models-dir", default=None, help="Base models dir for $MODELS_DIR expansion (default: $COMFY_HOME/models)")
    p.add_argument("--cache-dir", default=None, help="Cache directory for downloaded artifacts (default: $COMFY_HOME/.cache/models)")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing files if checksum mismatch and source is available")
    p.add_argument("--timeout", type=int, default=120, help="Network timeout in seconds for http(s)/gs downloads")
    p.add_argument("--verbose", action="store_true", help="Verbose output (per-model status)")
    p.add_argument("--cache", action="store_true", help="Enable using and writing cache (disabled by default)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return run_verification(
            lock_path=args.lock,
            models_dir=args.models_dir,
            cache_dir=args.cache_dir,
            overwrite=args.overwrite,
            timeout=args.timeout,
            verbose=args.verbose,
            use_cache=args.cache,
        )
    except FileNotFoundError as exc:
        log_error(str(exc))
        return 1
    except Exception as exc:
        log_error(f"unexpected error: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


