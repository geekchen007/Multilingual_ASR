"""Regression checks for the reorganized package and legacy entry point."""

import subprocess
import sys
from pathlib import Path

from asr_eval import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_cli_help_does_not_initialize_data(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "app.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    assert b"create-user" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_packaged_assets_work_from_another_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASR_PROVIDERS", str(ROOT / "config/providers.example.json"))
    app = create_app(tmp_path / "runtime", testing=True)
    client = app.test_client()
    assert client.get("/login").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert {p["kind"] for p in app.config["PROVIDERS"].values()} == {
        "qwen_asr",
        "fun_asr",
    }
