"""Tests for the SQLite database engine and FastAPI WebUI server."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import appcontrol
from fastapi.testclient import TestClient

from app_database import AppDatabase
from web_server import create_app


def test_app_database_atomic_operations(tmp_path):
    db_file = str(tmp_path / "test_app.db")
    db = AppDatabase(db_file)

    # Config
    db.set_config("test_num", 42)
    db.set_config("test_str", "hello")
    assert db.get_config("test_num") == 42
    assert db.get_config("test_str") == "hello"
    assert db.get_config("missing", "default") == "default"

    # Logging
    db.log_message("INFO", "TestMod", "Testing database logging")
    db.log_message("ERROR", "TestMod", "Error logged")
    logs = db.get_recent_logs(limit=10)
    assert len(logs) == 2
    assert logs[0]["message"] == "Testing database logging"
    assert logs[1]["message"] == "Error logged"

    # Audit
    db.record_audit({
        "id": "aud_1",
        "category": "ADB",
        "action": "devices",
        "command": "adb devices -l",
        "status": "SUCCESS",
        "duration_sec": 0.05
    })
    audits = db.get_recent_audits(10)
    assert len(audits) == 1
    assert audits[0]["action"] == "devices"

    # Mutation Journal
    db.record_mutation("m_1", "SERIAL_1", "disable", "com.test.pkg", "pm enable com.test.pkg", "Disable test")
    muts = db.get_mutations()
    assert len(muts) == 1
    assert muts[0]["package_name"] == "com.test.pkg"
    assert muts[0]["undone"] == 0

    db.mark_mutation_undone("m_1")
    assert len(db.get_mutations(pending_only=True)) == 0


def test_web_server_endpoints(tmp_path, monkeypatch):
    store = appcontrol.AppStateStore(appcontrol.AppConfig())
    app = create_app(store_provider=lambda: store)
    client = TestClient(app)

    # 1. Frontend HTML & CSS
    res = client.get("/")
    assert res.status_code == 200
    assert "ADB AppControl" in res.text
    assert "WEBUI" in res.text

    res_css = client.get("/style.css")
    assert res_css.status_code == 200
    assert "text/css" in res_css.headers["content-type"]
    assert "--bg-main" in res_css.text

    # 2. Status API
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "connected_devices_count" in data
    assert "server_time" in data

    # 3. Devices API
    res = client.get("/api/devices")
    assert res.status_code == 200
    assert "devices" in res.json()

    # 4. Apps API
    res = client.get("/api/apps")
    assert res.status_code == 200
    assert "apps" in res.json()
    assert "stats" in res.json()

    # 5. Settings API
    res = client.get("/api/settings")
    assert res.status_code == 200
    assert "settings" in res.json()

    res = client.post("/api/settings", json={"custom_scale": 1.25})
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 6. Journal API
    res = client.get("/api/journal")
    assert res.status_code == 200
    assert "mutations" in res.json()

    # 7. Logs API
    res = client.get("/api/logs")
    assert res.status_code == 200
    assert "logs" in res.json()

    # 8. AI Status API
    res = client.get("/api/ai/status")
    assert res.status_code == 200
    assert "ready" in res.json()
    assert "status" in res.json()

    # 9. Debloat Presets API
    res = client.get("/api/debloat/presets")
    assert res.status_code == 200
    assert "presets" in res.json()

    store.shutdown()
