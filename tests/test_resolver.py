import json
import os
from pathlib import Path

import pytest

from rp_handler import resolver


def test_derive_env_defaults(monkeypatch, tmp_path: Path):
    # No COMFY_HOME env -> default /runpod-volume/ComfyUI per resolver
    monkeypatch.delenv("COMFY_HOME", raising=False)
    env = resolver.derive_env(models_dir=None)
    assert env["COMFY_HOME"].endswith("/runpod-volume/ComfyUI")
    assert env["MODELS_DIR"].endswith("/runpod-volume/models")


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


def test_validate_version_spec_python_packages(tmp_path: Path):
    """Проверяет, что validate_version_spec корректно обрабатывает поле python_packages."""
    spec_file = tmp_path / "test.json"
    spec_data = {
        "schema_version": 2,
        "version_id": "test-version",
        "comfy": {
            "repo": "https://github.com/comfyanonymous/ComfyUI",
            "ref": "master",
            "commit": "abc123"
        },
        "custom_nodes": [],
        "models": [],
        "python_packages": ["sageattention", "onnx>=1.14", "onnxruntime-gpu"],
        "env": {},
        "options": {}
    }
    spec_file.write_text(json.dumps(spec_data), encoding="utf-8")
    
    validated = resolver.validate_version_spec(spec_data, spec_file)
    
    assert "python_packages" in validated
    assert isinstance(validated["python_packages"], list)
    assert len(validated["python_packages"]) == 3
    assert "sageattention" in validated["python_packages"]
    assert "onnx>=1.14" in validated["python_packages"]
    assert "onnxruntime-gpu" in validated["python_packages"]


def test_validate_version_spec_python_packages_optional(tmp_path: Path):
    """Проверяет, что python_packages опционально и можно не указывать."""
    spec_file = tmp_path / "test.json"
    spec_data = {
        "schema_version": 2,
        "version_id": "test-version",
        "comfy": {
            "repo": "https://github.com/comfyanonymous/ComfyUI",
            "ref": "master",
            "commit": "abc123"
        },
        "custom_nodes": [],
        "models": [],
        "env": {},
        "options": {}
    }
    spec_file.write_text(json.dumps(spec_data), encoding="utf-8")
    
    validated = resolver.validate_version_spec(spec_data, spec_file)
    
    assert "python_packages" in validated
    assert validated["python_packages"] == []


def test_validate_version_spec_python_packages_invalid_type(tmp_path: Path):
    """Проверяет, что невалидный тип python_packages вызывает ошибку."""
    spec_file = tmp_path / "test.json"
    spec_data = {
        "schema_version": 2,
        "version_id": "test-version",
        "comfy": {
            "repo": "https://github.com/comfyanonymous/ComfyUI",
            "ref": "master",
            "commit": "abc123"
        },
        "custom_nodes": [],
        "models": [],
        "python_packages": "not-a-list",  # должен быть список
        "env": {},
        "options": {}
    }
    spec_file.write_text(json.dumps(spec_data), encoding="utf-8")
    
    with pytest.raises(resolver.SpecValidationError) as exc_info:
        resolver.validate_version_spec(spec_data, spec_file)
    
    assert "python_packages" in str(exc_info.value)


