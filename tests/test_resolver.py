import json
import os
from pathlib import Path

import pytest

from rp_handler import resolver


def test_derive_env_defaults(monkeypatch, tmp_path: Path):
    # No COMFY_HOME env -> default /workspace/ComfyUI per resolver
    monkeypatch.delenv("COMFY_HOME", raising=False)
    env = resolver.derive_env(models_dir=None)
    assert env["COMFY_HOME"].endswith("/workspace/ComfyUI")
    assert env["MODELS_DIR"].endswith("/.cache/runpod-comfy/models")


def test_load_lock_missing_returns_empty(tmp_path: Path):
    data = resolver.load_lock(str(tmp_path / "nope.json"))
    assert data == {}


def test_install_python_packages_builds_pip_args(monkeypatch, tmp_path: Path, capsys):
    # Create a fake lock dict
    lock = {
        "python": {
            "packages": [
                {"name": "foo", "version": "1.2.3"},
                {"name": "bar", "url": "https://example/b.whl"},
                {"name": "baz"},
            ]
        }
    }

    # Stub run to avoid invoking pip
    calls = {"args": None}

    def fake_run(args, cwd=None, env=None):  # type: ignore[no-untyped-def]
        calls["args"] = args
        return 0, "ok", ""

    monkeypatch.setattr(resolver, "run_command", fake_run)

    resolver.install_python_packages(lock, verbose=True)

    assert calls["args"][0].endswith("python") or calls["args"][0].endswith("python3") or calls["args"][0].endswith(".exe")
    assert calls["args"][1:4] == ["-m", "pip", "install"]
    # Ensure entries are translated
    s = " ".join(calls["args"][4:])
    assert "foo==1.2.3" in s
    assert "bar @ https://example/b.whl" in s
    assert "baz" in s


def test_verify_and_fetch_models_invokes_script_if_present(monkeypatch, tmp_path: Path):
    # Вместо глобального патча pathlib.Path подменяем только exists для конкретного пути,
    # чтобы не ломать pytest и сторонний код
    vm = Path("/app/scripts/verify_models.py")

    def fake_exists(self):  # type: ignore[no-untyped-def]
        return str(self) == str(vm)

    monkeypatch.setattr(Path, "exists", fake_exists, raising=False)

    # Stub run to capture args
    called = {"args": None}

    def fake_run(args, cwd=None, env=None):  # type: ignore[no-untyped-def]
        called["args"] = args
        return 0, "ok", ""

    monkeypatch.setattr(resolver, "run_command", fake_run)

    env = {"MODELS_DIR": "/m"}
    resolver.verify_and_fetch_models(lock_path="/app/scripts/verify_models.py", env=env, verbose=True)
    assert called["args"][0].endswith("python") or called["args"][0].endswith("python3") or called["args"][0].endswith(".exe")


def test_apply_lock_and_prepare_smoke(monkeypatch):
    # Make load_lock return a small lock with packages
    monkeypatch.setattr(resolver, "load_lock", lambda p: {"python": {"packages": []}})

    called = {"pip": False, "verify": False}

    def fake_install(lock, verbose):  # type: ignore[no-untyped-def]
        called["pip"] = True

    def fake_verify(lock_path, env, verbose, no_cache):  # type: ignore[no-untyped-def]
        called["verify"] = True
        called["no_cache"] = no_cache

    monkeypatch.setattr(resolver, "install_python_packages", fake_install)
    monkeypatch.setattr(resolver, "verify_and_fetch_models", fake_verify)

    resolver.apply_lock_and_prepare(lock_path="lock.json", models_dir=None, verbose=True)
    assert called["pip"] is True
    assert called["verify"] is True
    assert called["no_cache"] is True


