import base64
import json
from pathlib import Path

from docker.handler import main as handler_main


def test_main_base64_to_stdout(tmp_path, capsys, monkeypatch):
    # Create a minimal lock file and a workflow file
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"python": {"packages": []}}), encoding="utf-8")
    wf = tmp_path / "wf.json"
    wf.write_text("{\n  \"graph\": {}\n}\n", encoding="utf-8")

    # Avoid actual pip/model verification
    monkeypatch.setattr(handler_main, "apply_lock_and_prepare", lambda lock_path, models_dir, verbose: None)

    code = handler_main.main([
        "--lock", str(lock),
        "--workflow", str(wf),
        "--output", "base64",
        "--verbose",
    ])
    assert code == 0
    out = capsys.readouterr().out.strip()
    # Should be base64 of the workflow content
    assert base64.b64decode(out) == wf.read_text(encoding="utf-8").encode("utf-8")


def test_main_gcs_invokes_emit(monkeypatch, tmp_path):
    # Prepare lock
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({}), encoding="utf-8")

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
    monkeypatch.setattr(handler_main, "apply_lock_and_prepare", lambda lock_path, models_dir, verbose: None)
    monkeypatch.setattr(handler_main, "emit_output", fake_emit)

    code = handler_main.main([
        "--lock", str(lock),
        "--workflow", str(tmp_path / "missing.json"),  # will fallback to PNG
        "--output", "gcs",
        "--gcs-bucket", "bkt",
        "--gcs-prefix", "pref",
    ])
    assert code == 0
    assert called["kwargs"]["mode"] == "gcs"
    assert called["kwargs"]["gcs_bucket"] == "bkt"
    assert called["kwargs"]["gcs_prefix"] == "pref"


