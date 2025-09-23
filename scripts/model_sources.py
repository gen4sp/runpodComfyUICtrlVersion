#!/usr/bin/env python3
"""
Helpers for model source URLs (civitai, huggingface):
- Build final download URLs and headers
- Determine artifact size in bytes

This module is intentionally dependency-free (stdlib only) for reuse from scripts.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple


# ------------------------------- Civitai helpers ------------------------------- #


def parse_civitai_source(source: str) -> str:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme != "civitai":
        raise ValueError("not a civitai url")
    # Compose path from netloc + path to support civitai://api/download/... form
    composed = "/".join(x for x in [parsed.netloc.strip("/"), parsed.path.lstrip("/")] if x)
    path = composed.strip("/")
    if not path:
        raise ValueError("Invalid civitai url. Expected civitai://models/<id> or civitai://api/download/models/<id>")
    # Keep query if present (for format/type hints)
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def civitai_build_download_url_and_headers(source: str) -> Tuple[str, Dict[str, str]]:
    path = parse_civitai_source(source)
    if path.startswith("api/download/models/"):
        url = f"https://civitai.com/{path}"
    elif path.startswith("models/"):
        # Convert shorthand civitai://models/<id> -> api download URL
        model_id = path.split("/")[-1]
        url = f"https://civitai.com/api/download/models/{model_id}"
    else:
        raise ValueError("Unsupported civitai path format")

    token = os.environ.get("CIVITAI_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return url, headers


def _http_head_content_length(url: str, timeout: int, headers: Optional[Dict[str, str]] = None) -> Optional[int]:
    req_headers = {"User-Agent": "runpod-comfy-yaml-verifier/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, method="HEAD", headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - user-controlled URLs expected
            length = resp.headers.get("Content-Length")
            if length:
                return int(length)
    except Exception:
        return None
    return None


def _extract_version_id_from_path(path: str) -> Optional[str]:
    # Supports: "api/download/models/<id>" and "models/<id>"
    if path.startswith("api/download/models/"):
        tail = path[len("api/download/models/"):]
        return tail.split("?", 1)[0].split("/", 1)[0]
    if path.startswith("download/models/"):
        tail = path[len("download/models/"):]
        return tail.split("?", 1)[0].split("/", 1)[0]
    if path.startswith("models/"):
        return path.split("/", 1)[1].split("/", 1)[0]
    return None


def _civitai_model_version_api_url(version_id: str) -> str:
    return f"https://civitai.com/api/v1/model-versions/{version_id}"


def _civitai_size_from_version_json(doc: Dict[str, object]) -> Optional[int]:
    files = doc.get("files") if isinstance(doc, dict) else None
    if not isinstance(files, list):
        return None
    chosen = None
    for f in files:
        if not isinstance(f, dict):
            continue
        fmt = str(f.get("format") or "").lower()
        name = str(f.get("name") or f.get("fileName") or "").lower()
        if fmt == "safetensor" or name.endswith(".safetensors"):
            chosen = f
            break
    if chosen is None and files:
        chosen = files[0]  # fallback to first
    if not isinstance(chosen, dict):
        return None
    size_kb = chosen.get("sizeKB")
    try:
        if isinstance(size_kb, (int, float)):
            return int(float(size_kb) * 1024)
    except Exception:
        return None
    return None


def civitai_get_size_bytes(source: str, timeout: int = 60) -> Optional[int]:
    # Try HEAD first
    url, headers = civitai_build_download_url_and_headers(source)
    length = _http_head_content_length(url, timeout=timeout, headers=headers)
    if isinstance(length, int) and length > 0:
        return length

    # Fallback to model-versions API
    path = parse_civitai_source(source)
    version_id = _extract_version_id_from_path(path)
    if not version_id:
        return None
    api_url = _civitai_model_version_api_url(version_id)
    req_headers = {"User-Agent": "runpod-comfy-yaml-verifier/1.0"}
    token = os.environ.get("CIVITAI_TOKEN")
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(api_url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - trusted host
            data = resp.read()
            doc = json.loads(data.decode("utf-8"))
            return _civitai_size_from_version_json(doc)
    except Exception:
        return None


# ----------------------------- HuggingFace helpers ---------------------------- #


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


def build_hf_resolve_url(repo_id: str, revision: str, path_in_repo: str) -> str:
    repo_id_quoted = "/".join(urllib.parse.quote(part, safe="") for part in repo_id.split("/"))
    path_quoted = urllib.parse.quote(path_in_repo.lstrip("/"), safe="/")
    rev_quoted = urllib.parse.quote(revision, safe="")
    return f"https://huggingface.co/{repo_id_quoted}/resolve/{rev_quoted}/{path_quoted}?download=true"


