import base64
import os
import types
from pathlib import Path

import pytest

from rp_handler.output import emit_output


def test_emit_output_base64_to_stdout(capsys):
    data = b"hello world"
    emit_output(data=data, mode="base64", out_file=None, gcs_bucket=None, gcs_prefix=None, verbose=False)
    captured = capsys.readouterr().out.strip()
    assert base64.b64decode(captured) == data


def test_emit_output_base64_to_file(tmp_path: Path):
    out_file = tmp_path / "out.txt"
    data = b"abc123"
    emit_output(data=data, mode="base64", out_file=str(out_file), gcs_bucket=None, gcs_prefix=None, verbose=True)
    text = out_file.read_text(encoding="utf-8").strip()
    assert base64.b64decode(text) == data


def test_emit_output_gcs_missing_dep(monkeypatch):
    # Force import error for google.cloud.storage
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name.startswith("google.cloud.storage") or name == "google.cloud" or name.startswith("google"):
            raise ImportError("no gcloud")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError) as exc:
        emit_output(data=b"x", mode="gcs", out_file=None, gcs_bucket="bucket", gcs_prefix=None, verbose=False)
    assert "google-cloud-storage" in str(exc.value)


def test_emit_output_gcs_requires_bucket(monkeypatch):
    # Provide a dummy google.cloud.storage module to pass the import
    dummy_mod = types.SimpleNamespace(Client=lambda project=None: None)
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "google.cloud.storage":
            return dummy_mod
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(RuntimeError) as exc:
        emit_output(data=b"x", mode="gcs", out_file=None, gcs_bucket=None, gcs_prefix=None, verbose=False)
    assert "GCS bucket is required" in str(exc.value)


def test_emit_output_gcs_requires_credentials(monkeypatch, tmp_path: Path):
    # Stub google.cloud.storage.Client and bucket APIs
    class DummyBlob:
        def __init__(self):
            self._uploaded = False

        def upload_from_string(self, data: bytes) -> None:
            self._uploaded = True

        def acl(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("not used in this test")

    class DummyBucket:
        def blob(self, name: str):  # type: ignore[no-untyped-def]
            return DummyBlob()

        def test_iam_permissions(self, perms):  # type: ignore[no-untyped-def]
            return perms

    class DummyClient:
        def __init__(self, project=None):  # type: ignore[no-untyped-def]
            pass

        def get_bucket(self, bucket_name):  # type: ignore[no-untyped-def]
            return DummyBucket()

        def bucket(self, bucket_name):  # type: ignore[no-untyped-def]
            return DummyBucket()

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "google.cloud.storage":
            mod = types.SimpleNamespace(Client=DummyClient)
            return mod
        return real_import(name, *args, **kwargs)

    monkeypatch.setenv("GCS_VALIDATE", "0")
    monkeypatch.setattr("builtins.__import__", fake_import)

    # No credentials -> should raise
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(RuntimeError) as exc:
        emit_output(data=b"x", mode="gcs", out_file=None, gcs_bucket="bucket", gcs_prefix="prefix", verbose=False)
    assert "GOOGLE_APPLICATION_CREDENTIALS" in str(exc.value)


def test_emit_output_gcs_happy_path(monkeypatch, tmp_path: Path, capsys):
    # Create a dummy credentials file
    creds = tmp_path / "creds.json"
    creds.write_text("{}", encoding="utf-8")

    uploaded = {"ok": False, "name": None}

    class DummyBlob:
        def __init__(self, name: str):
            self.name = name
            self._uploaded = False

        def upload_from_string(self, data: bytes) -> None:
            self._uploaded = True
            uploaded["ok"] = True
            uploaded["name"] = self.name

        def acl(self):  # type: ignore[no-untyped-def]
            class ACL:
                def all(self):  # type: ignore[no-untyped-def]
                    class All:
                        def grant_read(self):  # type: ignore[no-untyped-def]
                            return None
                    return All()

                def save(self):  # type: ignore[no-untyped-def]
                    return None

            return ACL()

        def generate_signed_url(self, expiration):  # type: ignore[no-untyped-def]
            return "https://signed"

    class DummyBucket:
        def __init__(self, name: str):
            self._name = name

        def blob(self, name: str):  # type: ignore[no-untyped-def]
            return DummyBlob(name)

        def test_iam_permissions(self, perms):  # type: ignore[no-untyped-def]
            return perms

    class DummyClient:
        def __init__(self, project=None):  # type: ignore[no-untyped-def]
            pass

        def get_bucket(self, bucket_name):  # type: ignore[no-untyped-def]
            return DummyBucket(bucket_name)

        def bucket(self, bucket_name):  # type: ignore[no-untyped-def]
            return DummyBucket(bucket_name)

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "google.cloud.storage":
            return types.SimpleNamespace(Client=DummyClient)
        return real_import(name, *args, **kwargs)

    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    monkeypatch.setenv("GCS_PUBLIC", "1")
    monkeypatch.setenv("GCS_SIGNED_URL_TTL", "60")
    monkeypatch.setenv("GCS_VALIDATE", "1")
    monkeypatch.setattr("builtins.__import__", fake_import)

    emit_output(data=b"payload", mode="gcs", out_file=None, gcs_bucket="my-bkt", gcs_prefix="pref", verbose=True)
    out = capsys.readouterr().out.strip()
    assert out.startswith("gs://my-bkt/")
    assert uploaded["ok"] is True


def test_emit_output_unknown_mode():
    with pytest.raises(ValueError):
        emit_output(data=b"x", mode="unknown", out_file=None, gcs_bucket=None, gcs_prefix=None, verbose=False)


