#!/usr/bin/env python3
from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import tempfile
import urllib.request
from typing import Any, Dict, Optional

try:
    import runpod  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError("runpod package is required for serverless adapter. Install 'runpod'.") from exc

from .main import spec_path_for_version
from .resolver import (
    SpecValidationError,
    resolve_version_spec,
    save_resolved_lock,
    realize_from_resolved,
)
from .workflow import run_workflow


def _download_to_temp(url: str) -> str:
    fd, tmp_path = tempfile.mkstemp(prefix="workflow_", suffix=".json")
    os.close(fd)
    with urllib.request.urlopen(url) as resp, open(tmp_path, "wb") as f:
        f.write(resp.read())
    return tmp_path


def _write_json_to_temp(data: Any) -> str:
    fd, tmp_path = tempfile.mkstemp(prefix="workflow_", suffix=".json")
    os.close(fd)
    # data может быть dict или строка JSON
    if isinstance(data, (dict, list)):
        payload = json.dumps(data, ensure_ascii=False)
    elif isinstance(data, str):
        payload = data
    else:
        raise ValueError("workflow must be a JSON object/array or JSON string")
    pathlib.Path(tmp_path).write_text(payload, encoding="utf-8")
    return tmp_path


def _gcs_upload(data: bytes, bucket: str, prefix: Optional[str]) -> Dict[str, Any]:
    try:
        storage = __import__("google.cloud.storage", fromlist=["Client"])  # type: ignore
    except Exception as exc:
        raise RuntimeError("google-cloud-storage is required for gcs output") from exc

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS must point to a readable service-account JSON file"
        )
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCS_PROJECT")
    client = storage.Client(project=project)  # uses GOOGLE_APPLICATION_CREDENTIALS

    bucket_obj = client.bucket(bucket)
    # simple path: <prefix>/<timestamp>-<rand>.bin
    import datetime as dt
    import uuid

    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    unique = uuid.uuid4().hex[:8]
    object_name = f"{prefix or 'comfy/outputs'}/{ts}-{unique}.bin"
    blob = bucket_obj.blob(object_name)
    blob.upload_from_string(data)

    url = f"gs://{bucket}/{object_name}"

    result: Dict[str, Any] = {"gcs_url": url}

    # Optional public-read
    if str(os.environ.get("GCS_PUBLIC", "")).strip().lower() in {"1", "true", "yes", "on"}:
        try:
            blob.acl.all().grant_read()
            blob.acl.save()
        except Exception:
            pass

    # Optional signed URL
    try:
        ttl = int(os.environ.get("GCS_SIGNED_URL_TTL", "0"))
    except ValueError:
        ttl = 0
    if ttl > 0:
        try:
            import datetime as dt

            signed = blob.generate_signed_url(expiration=dt.timedelta(seconds=ttl))
            result["signed_url"] = signed
        except Exception:
            pass

    return result


def _bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def handler(event: Dict[str, Any]) -> Dict[str, Any]:  # runpod serverless handler
    # Поддерживаем как event["input"], так и event напрямую
    payload: Dict[str, Any] = event.get("input") if isinstance(event, dict) else None  # type: ignore
    if not isinstance(payload, dict):
        payload = event if isinstance(event, dict) else {}

    version_id = payload.get("version_id") or os.environ.get("COMFY_VERSION_NAME")
    if not isinstance(version_id, str) or not version_id.strip():
        return {"error": "version_id is required"}

    workflow_file: Optional[str] = None
    try:
        if "workflow_url" in payload and isinstance(payload["workflow_url"], str):
            workflow_file = _download_to_temp(payload["workflow_url"])  # type: ignore[arg-type]
        elif "workflow" in payload:
            workflow_file = _write_json_to_temp(payload["workflow"])
        else:
            return {"error": "workflow or workflow_url must be provided"}

        # Output options
        output_mode = (payload.get("output_mode") or os.environ.get("OUTPUT_MODE") or "gcs").strip()
        gcs_bucket = payload.get("gcs_bucket") or os.environ.get("GCS_BUCKET")
        gcs_prefix = payload.get("gcs_prefix") or os.environ.get("GCS_PREFIX", "comfy/outputs")
        verbose = _bool(payload.get("verbose"), False)

        # 1) Resolve + realize version
        try:
            spec_path = spec_path_for_version(version_id)
        except ValueError as exc:
            return {"error": str(exc)}
        if not spec_path.exists():
            return {"error": f"Spec file not found for version '{version_id}': {spec_path}"}

        offline_env = str(os.environ.get("COMFY_OFFLINE", "")).strip().lower() in {"1", "true", "yes", "on"}
        try:
            resolved = resolve_version_spec(spec_path, offline=offline_env)
        except SpecValidationError as exc:
            return {"error": str(exc)}
        except RuntimeError as exc:
            return {"error": str(exc)}

        resolved_options = resolved.get("options") or {}
        offline_effective = bool(resolved_options.get("offline") or offline_env)
        skip_models_effective = bool(resolved_options.get("skip_models"))
        resolved["options"] = {
            **resolved_options,
            "offline": offline_effective,
            "skip_models": skip_models_effective,
        }

        save_resolved_lock(resolved)
        comfy_home_path, models_dir_path = realize_from_resolved(resolved, offline=offline_effective)

        # models_dir override
        models_dir_effective = pathlib.Path(payload.get("models_dir")).resolve() if isinstance(payload.get("models_dir"), str) else models_dir_path

        # 2) Run workflow
        try:
            artifact_bytes = run_workflow(workflow_file, str(comfy_home_path), str(models_dir_effective), verbose)
        except RuntimeError as exc:
            return {"error": str(exc)}

        # 3) Build output
        if output_mode == "base64":
            encoded = base64.b64encode(artifact_bytes).decode("utf-8")
            return {
                "version_id": version_id,
                "output_mode": "base64",
                "base64": encoded,
                "size": len(artifact_bytes),
            }
        elif output_mode == "gcs":
            if not gcs_bucket:
                return {"error": "GCS bucket is required for gcs output"}
            try:
                res = _gcs_upload(artifact_bytes, str(gcs_bucket), str(gcs_prefix) if gcs_prefix else None)
                res.update({
                    "version_id": version_id,
                    "output_mode": "gcs",
                    "size": len(artifact_bytes),
                })
                return res
            except Exception as exc:
                return {"error": f"GCS upload failed: {exc}"}
        else:
            return {"error": f"Unknown output mode: {output_mode}"}
    finally:
        try:
            if workflow_file and os.path.exists(workflow_file):
                os.remove(workflow_file)
        except Exception:
            pass


def _start_serverless() -> None:  # pragma: no cover
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":  # pragma: no cover
    _start_serverless()


