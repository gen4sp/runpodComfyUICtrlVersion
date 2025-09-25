import base64
import json
from pathlib import Path

from rp_handler import main as handler_main


def test_main_base64_to_stdout(tmp_path, capsys, monkeypatch):
    # Create a minimal spec file and a workflow file
    spec = tmp_path / "version.json"
    spec.write_text(json.dumps({
        "schema_version": 2,
        "version_id": "test",
        "comfy": {"repo": "https://github.com/comfyanonymous/ComfyUI"},
        "custom_nodes": [],
        "models": []
    }), encoding="utf-8")
    wf = tmp_path / "wf.json"
    wf.write_text("{\n  \"graph\": {}\n}\n", encoding="utf-8")

    # Stub heavy operations
    monkeypatch.setattr(handler_main, "resolve_version_spec", lambda p, offline=False: {
        "schema_version": 2,
        "version_id": "test",
        "comfy": {"repo": "https://github.com/comfyanonymous/ComfyUI", "commit": None},
        "custom_nodes": [],
        "models": []
    })
    monkeypatch.setattr(handler_main, "save_resolved_lock", lambda resolved: spec)  # type: ignore[misc]
    def fake_realize(resolved, offline=False):  # type: ignore[no-untyped-def]
        ch = tmp_path / "comfy"
        md = ch / "models"
        ch.mkdir(parents=True, exist_ok=True)
        md.mkdir(parents=True, exist_ok=True)
        return ch, md
    monkeypatch.setattr(handler_main, "realize_from_resolved", fake_realize)
    monkeypatch.setattr(handler_main, "run_workflow_real", lambda wf_path, comfy_home, models_dir, verbose: wf.read_bytes())

    code = handler_main.main([
        "--spec", str(spec),
        "--workflow", str(wf),
        "--output", "base64",
        "--verbose",
    ])
    assert code == 0
    out = capsys.readouterr().out.strip()
    # Should be base64 of the workflow content
    assert base64.b64decode(out) == wf.read_bytes()


def test_main_gcs_invokes_emit(monkeypatch, tmp_path):
    # Prepare minimal spec
    spec = tmp_path / "version.json"
    spec.write_text(json.dumps({
        "schema_version": 2,
        "version_id": "test",
        "comfy": {"repo": "https://github.com/comfyanonymous/ComfyUI"}
    }), encoding="utf-8")

    called = {"kwargs": None}

    def fake_emit(data, mode, out_file, gcs_bucket, gcs_prefix, verbose):  # type: ignore[no-untyped-def]
        called["kwargs"] = {
            "mode": mode,
            "gcs_bucket": gcs_bucket,
            "gcs_prefix": gcs_prefix,
            "out_file": out_file,
            "verbose": verbose,
        }

    # Skip heavy preparation
    monkeypatch.setattr(handler_main, "resolve_version_spec", lambda p, offline=False: {
        "schema_version": 2,
        "version_id": "test",
        "comfy": {"repo": "https://github.com/comfyanonymous/ComfyUI", "commit": None},
        "custom_nodes": [],
        "models": []
    })
    monkeypatch.setattr(handler_main, "save_resolved_lock", lambda resolved: spec)  # type: ignore[misc]
    def fake_realize(resolved, offline=False):  # type: ignore[no-untyped-def]
        ch = tmp_path / "comfy"
        md = ch / "models"
        ch.mkdir(parents=True, exist_ok=True)
        md.mkdir(parents=True, exist_ok=True)
        return ch, md
    monkeypatch.setattr(handler_main, "realize_from_resolved", fake_realize)
    monkeypatch.setattr(handler_main, "run_workflow_real", lambda wf_path, comfy_home, models_dir, verbose: b"")
    monkeypatch.setattr(handler_main, "emit_output", fake_emit)

    code = handler_main.main([
        "--spec", str(spec),
        "--workflow", str(tmp_path / "missing.json"),
        "--output", "gcs",
        "--gcs-bucket", "bkt",
        "--gcs-prefix", "pref",
    ])
    assert code == 0
    assert called["kwargs"]["mode"] == "gcs"
    assert called["kwargs"]["gcs_bucket"] == "bkt"
    assert called["kwargs"]["gcs_prefix"] == "pref"


