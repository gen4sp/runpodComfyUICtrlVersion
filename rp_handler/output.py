#!/usr/bin/env python3
from __future__ import annotations

import base64
import datetime as dt
import os
from typing import Optional
import time
import uuid


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _get_env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def _validate_gcs_permissions(client, bucket_name: str, verbose: bool) -> None:
    # Check bucket existence and basic permissions to create objects
    bucket = client.bucket(bucket_name)
    try:
        # get_bucket throws on NotFound/Forbidden which is what we want to surface
        client.get_bucket(bucket_name)
    except Exception as exc:
        raise RuntimeError(f"GCS bucket validation failed for '{bucket_name}': {exc}") from exc
    try:
        perms = bucket.test_iam_permissions(["storage.objects.create"])
        if "storage.objects.create" not in perms:
            raise RuntimeError("Service account lacks 'storage.objects.create' on the bucket")
    except Exception as exc:
        # test_iam_permissions may be restricted; only warn if it fails unexpectedly
        if verbose:
            log_warn(f"Could not verify IAM permissions explicitly: {exc}")


def _gcs_upload_with_retries(blob, data: bytes, max_attempts: int = 3, base_sleep: float = 0.5, verbose: bool = False) -> None:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            blob.upload_from_string(data)
            return
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                sleep_s = base_sleep * (2 ** (attempt - 1))
                if verbose:
                    log_warn(f"upload attempt {attempt} failed: {exc}; retrying in {sleep_s:.1f}s")
                time.sleep(sleep_s)
            else:
                break
    assert last_exc is not None
    raise RuntimeError(f"GCS upload failed after {max_attempts} attempts: {last_exc}") from last_exc


def emit_output(data: bytes, mode: str, out_file: Optional[str], gcs_bucket: Optional[str], gcs_prefix: Optional[str], verbose: bool) -> None:
    if mode == "base64":
        payload = base64.b64encode(data).decode("utf-8")
        if out_file:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(payload)
            if verbose:
                log_info(f"base64 saved to {out_file}")
        else:
            print(payload)
        return

    if mode == "gcs":
        try:
            storage = __import__("google.cloud.storage", fromlist=["Client"])  # type: ignore
        except Exception as exc:
            raise RuntimeError("google-cloud-storage is required for GCS output") from exc

        if not gcs_bucket:
            raise RuntimeError("GCS bucket is required for gcs output")

        # Credentials and project handling
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path or not os.path.exists(creds_path):
            raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS must point to a readable service-account JSON file")
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCS_PROJECT")
        client = storage.Client(project=project)  # uses GOOGLE_APPLICATION_CREDENTIALS

        if _get_env_bool("GCS_VALIDATE", True):
            _validate_gcs_permissions(client, gcs_bucket, verbose=verbose)

        bucket = client.bucket(gcs_bucket)
        prefix = gcs_prefix or os.environ.get("GCS_PREFIX", "comfy/outputs")
        timestamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        unique = uuid.uuid4().hex[:8]
        object_name = f"{prefix}/{timestamp}-{unique}.bin"
        blob = bucket.blob(object_name)

        # Retry upload with simple exponential backoff
        max_attempts = int(os.environ.get("GCS_RETRIES", "3"))
        base_sleep = float(os.environ.get("GCS_RETRY_BASE_SLEEP", "0.5"))
        _gcs_upload_with_retries(blob, data=data, max_attempts=max_attempts, base_sleep=base_sleep, verbose=verbose)

        url = f"gs://{gcs_bucket}/{object_name}"
        # Сначала печатаем URL, чтобы первая строка stdout начиналась с gs://
        print(url)
        if verbose:
            log_info(f"uploaded to {url}")
        
        # Optionally make object public
        if _get_env_bool("GCS_PUBLIC", False):
            try:
                blob.acl.all().grant_read()
                blob.acl.save()
            except Exception as exc:
                if verbose:
                    log_warn(f"Failed to set public-read ACL: {exc}")

        # Optionally generate a signed URL (logged in verbose mode)
        signed_ttl = int(os.environ.get("GCS_SIGNED_URL_TTL", "0"))
        signed_url: Optional[str] = None
        if signed_ttl > 0:
            try:
                signed_url = blob.generate_signed_url(expiration=dt.timedelta(seconds=signed_ttl))
                if verbose:
                    log_info(f"signed_url (ttl={signed_ttl}s): {signed_url}")
            except Exception as exc:
                if verbose:
                    log_warn(f"Failed to generate signed URL: {exc}")
        return

    raise ValueError(f"Unknown output mode: {mode}")



