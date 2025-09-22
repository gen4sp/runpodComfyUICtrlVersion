#!/usr/bin/env python3
from __future__ import annotations

import base64
import datetime as dt
import os
from typing import Optional


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_warn(msg: str) -> None:
    print(f"[WARN] {msg}")


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
            from google.cloud import storage  # type: ignore
        except Exception as exc:
            raise RuntimeError("google-cloud-storage is required for GCS output") from exc

        if not gcs_bucket:
            raise RuntimeError("GCS bucket is required for gcs output")
        client = storage.Client()  # relies on GOOGLE_APPLICATION_CREDENTIALS
        bucket = client.bucket(gcs_bucket)
        prefix = gcs_prefix or "comfy/outputs"
        timestamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        object_name = f"{prefix}/{timestamp}.bin"
        blob = bucket.blob(object_name)
        blob.upload_from_string(data)
        url = f"gs://{gcs_bucket}/{object_name}"
        print(url)
        if verbose:
            log_info(f"uploaded to {url}")
        return

    raise ValueError(f"Unknown output mode: {mode}")


