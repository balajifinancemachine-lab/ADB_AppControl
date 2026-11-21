"""
ADB AppControl Modern Web Server & REST / WebSocket Engine.
Powered by FastAPI, Uvicorn & WebSockets for zero-lag real-time device management.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import shlex
import sys
import threading
import time
import webbrowser
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response

from app_database import APP_DB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

LOGGER = logging.getLogger("ADBAppControl")


def _device_to_dict(d: Any) -> dict[str, Any]:
    if d is None:
        return {}
    if hasattr(d, "to_dict"):
        try:
            return d.to_dict()
        except Exception:
            pass
    return {
        "serial": getattr(d, "serial", ""),
        "state": getattr(d, "state", "device"),
        "transport_mode": getattr(d, "transport_mode", "adb"),
        "device_model": getattr(d, "device_model", "Android Device"),
        "name": getattr(d, "name", ""),
        "android_version": getattr(d, "android_version", "Unknown"),
        "battery_level": getattr(d, "battery_level", None),
        "battery_status": getattr(d, "battery_status", ""),
        "battery_display": getattr(d, "get_battery_status", lambda: "")() if hasattr(d, "get_battery_status") else "",
        "specs": getattr(d, "specs", {}),
    }


def create_app(store_provider=None) -> FastAPI:
    # ── WEBSOCKET CLIENT MANAGER (REAL-TIME STREAMING) ────────────────────────
    class ConnectionManager:
        def __init__(self):
            self.active_connections: list[WebSocket] = []
            self._lock = asyncio.Lock()

        async def connect(self, websocket: WebSocket):
            await websocket.accept()
            async with self._lock:
                self.active_connections.append(websocket)

        async def disconnect(self, websocket: WebSocket):
            async with self._lock:
                if websocket in self.active_connections:
                    self.active_connections.remove(websocket)

        async def broadcast(self, message: dict[str, Any]):
            async with self._lock:
                to_remove = []
                for connection in self.active_connections:
                    try:
                        await connection.send_text(json.dumps(message))
                    except Exception:
                        to_remove.append(connection)
                for conn in to_remove:
                    if conn in self.active_connections:
                        self.active_connections.remove(conn)

    manager = ConnectionManager()
    loop_holder: dict[str, Any] = {"loop": None}

    def _get_store():
        if callable(store_provider):
            return store_provider()
        return store_provider

    def _broadcast_sync(msg_type: str, data: Any):
        loop = loop_holder.get("loop")
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": msg_type, "data": data, "timestamp": time.strftime("%H:%M:%S")}),
                loop
            )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        loop_holder["loop"] = asyncio.get_running_loop()
        store = _get_store()
        if store and hasattr(store, "adb_engine"):
            # Hook audit logger to broadcast to browser
            def _on_audit(rec):
                _broadcast_sync("audit", rec.to_dict())
                APP_DB.record_audit(rec.to_dict())

            from appcontrol import AUDIT_LOGGER
            AUDIT_LOGGER.subscribe(_on_audit)

            # SQLite log handler hook
            class WsLogHandler(logging.Handler):
                def emit(self, record):
                    try:
                        msg = record.getMessage()
                        APP_DB.log_message(record.levelname, record.name, msg)
                        _broadcast_sync("log", {
                            "level": record.levelname,
                            "logger": record.name,
                            "message": msg,
                            "time": time.strftime("%H:%M:%S")
                        })
                    except Exception:
                        pass
            ws_h = WsLogHandler()
            ws_h.setLevel(logging.INFO)
            LOGGER.addHandler(ws_h)
        yield

    app = FastAPI(title="ADB AppControl Modern WebUI", version="3.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.websocket("/ws/live")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        # Send initial recent logs and device status on connect
        try:
            recent_logs = APP_DB.get_recent_logs(80)
            recent_audits = APP_DB.get_recent_audits(50)
            await websocket.send_text(json.dumps({
                "type": "init",
                "logs": recent_logs,
                "audits": recent_audits,
                "timestamp": time.strftime("%H:%M:%S")
            }))
            while True:
                data = await websocket.receive_text()
                # Heartbeat or client ping
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            await manager.disconnect(websocket)
        except Exception:
            await manager.disconnect(websocket)

    # ── SYSTEM & STATUS APIS ──────────────────────────────────────────────────
    @app.get("/api/status")
    def get_status():
        store = _get_store()
        if not store:
            return {"error": "Store not initialized"}
        cur = store.get_current_device()
        devs = store.get_device_list()
        brain = getattr(store, "brain_engine", None)
        return {
            "connected_devices_count": len(devs),
            "current_device": _device_to_dict(cur) if cur else None,
            "acbridge_ready": store.is_acbridge_ready(),
            "ai_model_ready": getattr(brain, "is_ready", False) if brain else False,
            "ai_status": getattr(brain, "status_msg", "Offline") if brain else "Offline",
            "server_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    @app.get("/api/devices")
    def list_devices():
        store = _get_store()
        devs = store.get_device_list()
        cur = store.get_current_device()
        return {
            "devices": [_device_to_dict(d) for d in devs],
            "active_serial": cur.serial if cur else ""
        }

    @app.post("/api/devices/select")
    def select_device(payload: dict[str, str]):
        serial = payload.get("serial", "").strip()
        store = _get_store()
        devs = store.get_device_list()
        for d in devs:
            if d.serial == serial:
                store.set_current_device(d)
                # Refresh apps for device
                apps = store.adb_engine.list_all_packages()
                store.update_app_data(apps)
                APP_DB.cache_packages(serial, apps)
                _broadcast_sync("device_changed", {"serial": serial, "model": d.device_model})
                return {"success": True, "device": _device_to_dict(d)}
        return {"success": False, "error": f"Device {serial} not found"}

    @app.post("/api/devices/scan")
    def trigger_scan():
        store = _get_store()
        devs = store.adb_engine.scan_devices(include_fastboot=True)
        cur = store.adb_engine.current_device
        apps = store.adb_engine.list_all_packages() if (cur and cur.state == "device") else []
        is_bridge = store.adb_engine.is_acbridge_installed() if (cur and cur.state == "device") else False
        store.batch_update_scan_results(devs, apps, is_bridge)
        if cur:
            APP_DB.cache_packages(cur.serial, apps)
        _broadcast_sync("scan_complete", {"devices": [_device_to_dict(d) for d in devs], "app_count": len(apps)})
        return {"success": True, "device_count": len(devs), "app_count": len(apps)}

    @app.post("/api/devices/reboot")
    def reboot_device(payload: dict[str, str]):
        target = payload.get("target", "system").lower()
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if target == "recovery":
            ok, out, err = engine.run_adb(["reboot", "recovery"], target_serial=serial)
        elif target == "bootloader":
            ok, out, err = engine.run_adb(["reboot", "bootloader"], target_serial=serial)
        elif target == "edl":
            ok, out, err = engine.run_adb(["reboot", "edl"], target_serial=serial)
        elif target == "fastboot":
            ok, out, err = engine.run_adb(["reboot", "fastboot"], target_serial=serial)
        else:
            ok, out, err = engine.run_adb(["reboot"], target_serial=serial)
        return {"success": ok, "message": (out or err).strip() or f"Reboot to {target} executed."}

    @app.post("/api/devices/wireless/connect")
    def connect_wireless(payload: dict[str, str]):
        address = payload.get("address", "").strip()
        if not address:
            raise HTTPException(status_code=400, detail="Address required (e.g. 192.168.1.100:5555)")
        store = _get_store()
        ok, out, err = store.adb_engine.run_adb(["connect", address], timeout=15)
        # Save to history
        hist = APP_DB.get_config("wireless_history", [])
        if address not in hist:
            hist.append(address)
            APP_DB.set_config("wireless_history", hist[-10:])
        return {"success": ok, "message": (out or err).strip()}

    @app.post("/api/devices/wireless/pair")
    def pair_wireless(payload: dict[str, str]):
        address = payload.get("address", "").strip()
        code = payload.get("code", "").strip()
        if not address or not code:
            raise HTTPException(status_code=400, detail="Address and pairing code required")
        store = _get_store()
        ok, out, err = store.adb_engine.run_adb(["pair", address, code], timeout=20)
        return {"success": ok, "message": (out or err).strip()}

    @app.get("/api/devices/specs")
    def get_specs():
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if hasattr(engine, "get_device_specs"):
            specs = engine.get_device_specs(serial=serial)
        else:
            specs = {}
        return {"specs": specs, "serial": serial}

    @app.post("/api/devices/mtp")
    def open_mtp():
        store = _get_store()
        engine = store.adb_engine
        msg = engine.open_native_mtp_explorer() if hasattr(engine, "open_native_mtp_explorer") else "MTP not supported"
        return {"success": True, "message": msg}

    @app.post("/api/devices/devmode")
    def enable_devmode():
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        msg = engine.enable_developer_mode(serial=serial) if hasattr(engine, "enable_developer_mode") else "Developer mode not supported"
        return {"success": True, "message": msg}

    @app.post("/api/devices/disconnect")
    def disconnect_device():
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if ":" in serial:
            engine.run_adb(["disconnect", serial])
        store.set_current_device(None)
        return {"success": True, "message": f"Disconnected {serial}"}

    @app.post("/api/devices/acbridge/install")
    def install_acbridge():
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        msg = engine.install_acbridge(serial=serial) if hasattr(engine, "install_acbridge") else "AC Bridge install not supported"
        return {"success": "successfully" in msg.lower(), "message": msg}

    # ── APPLICATION MANAGEMENT APIS ───────────────────────────────────────────
    @app.get("/api/apps")
    def get_applications(search: str = "", filter_type: str = "all", sort_by: str = "name"):
        store = _get_store()
        cur = store.get_current_device()
        if not cur or cur.state != "device":
            return {"apps": [], "stats": {"total": 0, "user": 0, "system": 0, "disabled": 0, "uninstalled": 0}}

        all_apps = store.get_all_apps()
        if not all_apps:
            # Check SQLite package cache first for instant response
            cached = APP_DB.get_cached_packages(cur.serial)
            if cached:
                all_apps = cached
                store.update_app_data(cached)
            else:
                all_apps = store.adb_engine.list_all_packages()
                store.update_app_data(all_apps)
                APP_DB.cache_packages(cur.serial, all_apps)

        stats = {
            "total": len(all_apps),
            "user": sum(1 for a in all_apps if not a.get("system")),
            "system": sum(1 for a in all_apps if a.get("system")),
            "disabled": sum(1 for a in all_apps if a.get("disabled")),
            "uninstalled": sum(1 for a in all_apps if a.get("uninstalled")),
        }

        # Filter
        res = []
        q = search.lower().strip()
        for a in all_apps:
            pkg = a.get("package", "")
            name = a.get("name", "") or a.get("label", "") or pkg
            if q and (q not in pkg.lower() and q not in name.lower()):
                continue
            if filter_type == "user" and a.get("system"):
                continue
            if filter_type == "system" and not a.get("system"):
                continue
            if filter_type == "disabled" and not a.get("disabled"):
                continue
            if filter_type == "uninstalled" and not a.get("uninstalled"):
                continue
            res.append(a)

        # Sort
        if sort_by == "package":
            res.sort(key=lambda x: x.get("package", "").lower())
        else:
            res.sort(key=lambda x: (x.get("name") or x.get("package", "")).lower())

        return {"apps": res, "stats": stats}

    @app.post("/api/apps/action")
    def perform_app_action(payload: dict[str, Any]):
        action = payload.get("action", "").lower().strip()
        packages = payload.get("packages", [])
        backup = payload.get("backup", True)
        user_zero = payload.get("user_zero", True)

        if not packages or not action:
            raise HTTPException(status_code=400, detail="Action and packages list required")

        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""

        results = []
        for pkg in packages:
            msg = ""
            ok = False
            if action == "uninstall":
                if backup:
                    engine.backup_apk(pkg, serial=serial)
                res = engine.uninstall_app(pkg, keep_data=False, user_zero=user_zero, serial=serial)
                ok = getattr(res, "ok", True)
                msg = str(res)
                if ok:
                    APP_DB.record_mutation(f"uninst_{int(time.time()*1000)}", serial, "uninstall", pkg, f"pm install-existing {pkg}", f"Uninstall {pkg}")
            elif action == "disable":
                res = engine.disable_app(pkg, serial=serial)
                ok = getattr(res, "ok", True)
                msg = str(res)
                if ok:
                    APP_DB.record_mutation(f"dis_{int(time.time()*1000)}", serial, "disable", pkg, f"pm enable {pkg}", f"Disable {pkg}")
            elif action == "enable":
                res = engine.enable_app(pkg, serial=serial)
                ok = getattr(res, "ok", True)
                msg = str(res)
            elif action == "clear":
                res = engine.clear_app_data(pkg, serial=serial)
                ok = getattr(res, "ok", True)
                msg = str(res)
            elif action == "backup":
                ok, msg = engine.backup_apk(pkg, serial=serial)
            elif action == "restore":
                res = engine.restore_uninstalled_app(pkg, serial=serial)
                ok = getattr(res, "ok", True)
                msg = str(res)
            elif action == "auto-permissions":
                g, tot = engine.auto_grant_all_permissions(pkg, serial=serial)
                ok = (g > 0 or tot == 0)
                msg = f"Granted {g}/{tot} permissions for {pkg}"
            elif action == "launch":
                ok, msg = engine.launch_app(pkg, serial=serial)
            elif action == "stop":
                ok, msg = engine.force_stop_app(pkg, serial=serial)
            else:
                msg = f"Unknown action '{action}'"
            results.append({"package": pkg, "success": ok, "message": msg})

        # Refresh package list in background
        threading.Thread(target=lambda: store.update_app_data(engine.list_all_packages()), daemon=True).start()
        return {"success": True, "results": results}

    @app.post("/api/apps/upload_install")
    async def upload_and_install_apk(
        files: list[UploadFile] = File(...),
        replace: bool = True,
        grant_perms: bool = True,
        downgrade: bool = False,
        test_pkg: bool = False,
    ):
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if not cur:
            raise HTTPException(status_code=400, detail="No device connected")

        upload_dir = os.path.join(DATA_DIR, "cache", "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        saved_paths = []
        for file in files:
            file_path = os.path.join(upload_dir, file.filename)
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)
            saved_paths.append(file_path)

        ok, msg = engine.install_apks(
            saved_paths,
            replace=replace,
            downgrade=downgrade,
            grant_perms=grant_perms,
            test_pkg=test_pkg,
            serial=serial,
        )
        return {"success": ok, "message": msg, "files": [f.filename for f in files]}

    @app.get("/api/apps/details/{pkg}")
    def get_app_details(pkg: str):
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        details = engine.get_package_details(pkg, serial=serial)
        return {"package": pkg, "details": details}

    @app.get("/api/apps/icon/{pkg}")
    def get_app_icon(pkg: str):
        icon_path = os.path.join(DATA_DIR, "cache", "icons", f"{pkg}.png")
        if os.path.isfile(icon_path):
            with open(icon_path, "rb") as f:
                return Response(content=f.read(), media_type="image/png")
        # Return generated SVG badge for zero network or disk overhead
        color_palette = ["#1E88E5", "#43A047", "#E53935", "#8E24AA", "#FB8C00", "#00ACC1", "#3949AB"]
        h = sum(ord(c) for c in pkg)
        color = color_palette[h % len(color_palette)]
        char = (pkg.split(".")[-1][0] if "." in pkg else pkg[0]).upper()
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">
            <rect width="40" height="40" rx="10" fill="{color}"/>
            <text x="20" y="26" font-family="system-ui, -apple-system, sans-serif" font-size="18" font-weight="bold" fill="white" text-anchor="middle">{char}</text>
        </svg>"""
        return Response(content=svg, media_type="image/svg+xml")

    # ── DEBLOAT WIZARD & PRESETS APIS ─────────────────────────────────────────
    @app.get("/api/debloat/presets")
    def get_debloat_presets():
        presets = [
            {"id": "safe", "name": "Recommended Safe Debloat", "description": "Safe telemetry & bloat removal"},
            {"id": "samsung", "name": "Samsung One UI Bloatware", "description": "Samsung Bixby, AR zone, and telemetry"},
            {"id": "xiaomi", "name": "Xiaomi / MIUI / HyperOS", "description": "Xiaomi Analytics, Mi Pay, and ads"},
            {"id": "google", "name": "Google Services & Telemetry", "description": "Google tracking and optional apps"},
            {"id": "carrier", "name": "Carrier Bloatware", "description": "Verizon, AT&T, T-Mobile carrier apps"}
        ]
        return {"presets": presets}

    @app.post("/api/debloat/apply")
    def apply_debloat(payload: dict[str, Any]):
        packages = payload.get("packages", [])
        action = payload.get("action", "disable")  # disable | uninstall
        backup = payload.get("backup", True)
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""

        results = []
        for pkg in packages:
            if action == "uninstall":
                if backup:
                    engine.backup_apk(pkg, serial=serial)
                res = engine.uninstall_app(pkg, keep_data=False, serial=serial)
            else:
                res = engine.disable_app(pkg, serial=serial)
            results.append({"package": pkg, "success": getattr(res, "ok", True), "message": str(res)})
        return {"success": True, "results": results}

    # ── PROCESS MANAGER APIS ──────────────────────────────────────────────────
    @app.get("/api/processes")
    def list_processes():
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if hasattr(engine, "get_process_list"):
            raw_procs = engine.get_process_list(serial=serial)
        elif hasattr(engine, "list_running_processes"):
            raw_procs = engine.list_running_processes(serial=serial)
        else:
            raw_procs = []
        procs = []
        for p in raw_procs:
            procs.append({
                "pid": p.get("pid", ""),
                "user": p.get("user", ""),
                "cpu": p.get("cpu", "0.0"),
                "ram": f"{p.get('ram_mb', 0)} MB" if "ram_mb" in p else p.get("ram", "0 MB"),
                "name": p.get("name", ""),
            })
        return {"processes": procs, "count": len(procs)}

    @app.post("/api/processes/kill")
    def kill_process(payload: dict[str, Any]):
        pid = payload.get("pid")
        pkg = payload.get("package", "")
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if pid:
            ok, out, err = engine.run_shell(f"kill -9 {pid}", target_serial=serial)
        elif pkg:
            ok, out = engine.force_stop_app(pkg, serial=serial)
            err = ""
        else:
            raise HTTPException(status_code=400, detail="PID or package required")
        return {"success": ok, "message": (out or err).strip() or "Process terminated."}

    @app.post("/api/processes/trim")
    def trim_ram():
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, msg = engine.trim_memory(serial=serial)
        return {"success": ok, "message": msg}

    # ── PERMISSIONS APIS ──────────────────────────────────────────────────────
    @app.get("/api/permissions/list")
    def get_supported_permissions():
        perms_dict = {
            "📷 Camera": "android.permission.CAMERA",
            "🎤 Microphone": "android.permission.RECORD_AUDIO",
            "📍 Location (Fine)": "android.permission.ACCESS_FINE_LOCATION",
            "📍 Location (Coarse)": "android.permission.ACCESS_COARSE_LOCATION",
            "📞 Phone State": "android.permission.READ_PHONE_STATE",
            "👥 Contacts (Read)": "android.permission.READ_CONTACTS",
            "👥 Contacts (Write)": "android.permission.WRITE_CONTACTS",
            "📅 Calendar": "android.permission.READ_CALENDAR",
            "📁 Storage (Read)": "android.permission.READ_EXTERNAL_STORAGE",
            "📁 Storage (Write)": "android.permission.WRITE_EXTERNAL_STORAGE",
            "📁 All Files Access": "android.permission.MANAGE_EXTERNAL_STORAGE",
            "💬 SMS Messages": "android.permission.READ_SMS",
            "📞 Call Log": "android.permission.READ_CALL_LOG",
            "🖼 Media & Photos": "android.permission.READ_MEDIA_IMAGES",
            "🎬 Media Video": "android.permission.READ_MEDIA_VIDEO",
            "🔔 Notifications": "android.permission.POST_NOTIFICATIONS",
            "📡 Nearby Bluetooth": "android.permission.BLUETOOTH_CONNECT",
            "🪟 Draw Over Apps": "android.permission.SYSTEM_ALERT_WINDOW",
            "⚙️ Modify Settings": "android.permission.WRITE_SETTINGS",
            "📊 Usage Stats Access": "android.permission.PACKAGE_USAGE_STATS",
            "🔋 Battery Unrestricted": "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
            "🗺️ Background Location": "android.permission.ACCESS_BACKGROUND_LOCATION",
            "🔢 Phone Numbers": "android.permission.READ_PHONE_NUMBERS",
        }
        return {"permissions": perms_dict}

    @app.get("/api/permissions/scan")
    def scan_permission(perm: str = "android.permission.CAMERA"):
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if hasattr(engine, "scan_all_permissions_for"):
            data = engine.scan_all_permissions_for(perm, serial=serial)
        else:
            data = {"granted": [], "revoked": []}
        return {"permission": perm, "granted": data.get("granted", []), "revoked": data.get("revoked", [])}

    @app.post("/api/permissions/batch")
    def batch_permission_change(payload: dict[str, Any]):
        action = payload.get("action", "grant")
        perm = payload.get("permission", "")
        packages = payload.get("packages", [])
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        results = []
        for pkg in packages:
            if action == "grant":
                res = engine.grant_permission(pkg, perm, serial=serial)
            else:
                res = engine.revoke_permission(pkg, perm, serial=serial)
            results.append({"package": pkg, "success": getattr(res, "ok", True), "message": str(res)})
        return {"success": True, "results": results}

    @app.get("/api/permissions")
    def list_permissions():
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        perms = engine.scan_runtime_permissions(serial=serial) if hasattr(engine, "scan_runtime_permissions") else []
        return {"permissions": perms}

    @app.post("/api/permissions/set")
    def set_permission(payload: dict[str, Any]):
        pkg = payload.get("package", "").strip()
        perm = payload.get("permission", "").strip()
        grant = payload.get("grant", True)
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if grant:
            ok, msg = engine.grant_permission(pkg, perm, serial=serial)
        else:
            ok, msg = engine.revoke_permission(pkg, perm, serial=serial)
        return {"success": ok, "message": msg}

    # ── SCREEN MIRRORING & SCREENSHOT APIS ─────────────────────────────────────
    @app.get("/api/screen/screenshot")
    def capture_screenshot():
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        shot_path = os.path.join(DATA_DIR, "screenshots", "live_shot.png")
        os.makedirs(os.path.dirname(shot_path), exist_ok=True)
        ok = engine.take_screenshot(output_path=shot_path, serial=serial)
        if not ok or not os.path.isfile(shot_path):
            raise HTTPException(status_code=500, detail="Failed to capture screenshot from device.")
        with open(shot_path, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode("utf-8")
        return {"success": True, "image_base64": f"data:image/png;base64,{b64_img}"}

    @app.post("/api/screen/scrcpy")
    def launch_scrcpy(payload: dict[str, Any]):
        max_size = payload.get("max_size", "")
        bitrate = payload.get("bitrate", "")
        fps = payload.get("fps", "")
        turn_screen_off = payload.get("turn_screen_off", False)
        stay_awake = payload.get("stay_awake", True)

        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, msg = engine.launch_scrcpy(
            max_size=max_size,
            bitrate=bitrate,
            fps=fps,
            turn_screen_off=turn_screen_off,
            stay_awake=stay_awake,
            serial=serial
        )
        return {"success": ok, "message": msg}

    @app.post("/api/screen/tap")
    def tap_screen(payload: dict[str, int]):
        x = payload.get("x", 0)
        y = payload.get("y", 0)
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, out, err = store.adb_engine.run_shell(f"input tap {x} {y}", target_serial=serial)
        return {"success": ok}

    @app.post("/api/screen/swipe")
    def handle_screen_swipe(payload: dict[str, Any]):
        x1 = payload.get("x1", 540)
        y1 = payload.get("y1", 1200)
        x2 = payload.get("x2", 540)
        y2 = payload.get("y2", 600)
        duration_ms = payload.get("duration", 250)
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, out, err = store.adb_engine.run_shell(
            f"input swipe {x1} {y1} {x2} {y2} {duration_ms}",
            target_serial=serial
        )
        return {"success": ok, "message": (out or err).strip()}

    @app.post("/api/screen/key")
    def send_keycode(payload: dict[str, Any]):
        key = payload.get("key", 3)
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, out, err = store.adb_engine.run_shell(f"input keyevent {key}", target_serial=serial)
        return {"success": ok}

    @app.post("/api/screen/text")
    def send_device_text(payload: dict[str, str]):
        text = payload.get("text", "")
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        msg = store.adb_engine.send_text(text, serial=serial) if hasattr(store.adb_engine, "send_text") else ""
        return {"success": True, "message": msg}

    @app.post("/api/screen/scale")
    def set_screen_scale(payload: dict[str, Any]):
        res = payload.get("resolution", "").strip()
        dpi = payload.get("density", "").strip()
        reset = payload.get("reset", False)
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if reset:
            store.adb_engine.set_display_size("", serial=serial)
            store.adb_engine.set_display_density("", serial=serial)
            return {"success": True, "message": "Display scaling reset to default"}
        if res:
            store.adb_engine.set_display_size(res, serial=serial)
        if dpi:
            store.adb_engine.set_display_density(dpi, serial=serial)
        return {"success": True, "message": f"Applied resolution={res} dpi={dpi}"}

    @app.get("/api/screen/clipboard")
    def get_clipboard():
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        txt = store.adb_engine.get_clipboard(serial=serial) if hasattr(store.adb_engine, "get_clipboard") else ""
        return {"clipboard": txt}

    @app.post("/api/screen/clipboard")
    def set_clipboard(payload: dict[str, str]):
        txt = payload.get("text", "")
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        msg = store.adb_engine.set_clipboard(txt, serial=serial) if hasattr(store.adb_engine, "set_clipboard") else ""
        return {"success": True, "message": msg}

    @app.post("/api/screen/record")
    def record_screen(payload: dict[str, Any]):
        sec = int(payload.get("seconds", 15))
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        dest_dir = store.adb_engine.get_device_dir("video", serial) if hasattr(store.adb_engine, "get_device_dir") else os.path.join(DATA_DIR, "video")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"record_{int(time.time())}.mp4")
        msg = store.adb_engine.start_screen_record(sec, dest, serial=serial) if hasattr(store.adb_engine, "start_screen_record") else ""
        return {"success": True, "message": msg, "saved_path": dest}

    # ── REMOTE FILE EXPLORER APIS ──

    # ── FILE EXPLORER & INSTALL APIS ──────────────────────────────────────────
    @app.get("/api/files/list")
    def list_files(path: str = "/sdcard/"):
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        files = engine.list_files(path, serial=serial)
        return {"path": path, "files": files}

    @app.post("/api/files/pull")
    def pull_file(payload: dict[str, str]):
        remote_path = payload.get("remote_path", "").strip()
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        dest_dir = os.path.join(DATA_DIR, "downloads")
        os.makedirs(dest_dir, exist_ok=True)
        dest_file = os.path.join(dest_dir, os.path.basename(remote_path))
        ok, msg = engine.pull_file(remote_path, dest_file, serial=serial)
        return {"success": ok, "message": msg, "saved_path": dest_file if ok else ""}

    @app.post("/api/files/push")
    def push_file(payload: dict[str, str]):
        local_path = payload.get("local_path", "").strip()
        remote_path = payload.get("remote_path", "/sdcard/").strip()
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, msg = engine.push_file(local_path, remote_path, serial=serial)
        return {"success": ok, "message": msg}

    @app.post("/api/files/mkdir")
    def make_directory(payload: dict[str, str]):
        path = payload.get("path", "").strip()
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, out, err = store.adb_engine.run_shell(f"mkdir -p {shlex.quote(path)}", target_serial=serial)
        return {"success": ok, "message": (out or err).strip()}

    @app.post("/api/files/delete")
    def delete_file(payload: dict[str, str]):
        path = payload.get("path", "").strip()
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, msg = store.adb_engine.delete_remote(path, serial=serial) if hasattr(store.adb_engine, "delete_remote") else (False, "Not supported")
        return {"success": ok, "message": msg}

    @app.get("/api/rescue/logcat")
    def get_logcat(lines: int = 200, filter: str = ""):
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        cmd = f"logcat -d -t {lines}"
        ok, out, err = store.adb_engine.run_shell(cmd, target_serial=serial)
        raw_lines = out.splitlines() if ok else []
        if filter:
            raw_lines = [l for l in raw_lines if filter.lower() in l.lower()]
        return {"lines": raw_lines[-lines:], "count": len(raw_lines)}

    @app.post("/api/rescue/logcat/clear")
    def clear_logcat():
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        msg = store.adb_engine.clear_logcat(serial=serial) if hasattr(store.adb_engine, "clear_logcat") else ""
        return {"success": True, "message": msg}

    @app.post("/api/rescue/bootloop_fix")
    def run_bootloop_fix(payload: dict[str, str]):
        fix_type = payload.get("fix_type", "safemode")
        store = _get_store()
        if hasattr(store.adb_engine, "bootloop_catch_and_fix"):
            res = store.adb_engine.bootloop_catch_and_fix(fix_type, timeout_sec=20)
        else:
            res = "Bootloop fixer not supported on this engine."
        return {"success": True, "message": res}

    @app.post("/api/rescue/root_action")
    def run_root_action(payload: dict[str, str]):
        action = payload.get("action", "diagnostic")
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if action == "diagnostic":
            status = store.adb_engine.get_root_status(serial=serial) if hasattr(store.adb_engine, "get_root_status") else "Unknown"
            return {"success": True, "message": f"Root Status: {status}"}
        elif action == "magisk":
            ok, msg = store.adb_engine.install_magisk_app(serial=serial) if hasattr(store.adb_engine, "install_magisk_app") else (False, "Not supported")
            return {"success": ok, "message": msg}
        elif action == "one_click_root":
            ok, msg = store.adb_engine.one_click_root(serial=serial) if hasattr(store.adb_engine, "one_click_root") else (False, "Not supported")
            return {"success": ok, "message": msg}
        return {"success": False, "message": f"Unknown root action: {action}"}

    @app.post("/api/rescue/fastboot")
    def run_fastboot_action(payload: dict[str, Any]):
        action = payload.get("action", "getvar")
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if action == "getvar":
            if hasattr(store.adb_engine, "get_fastboot_vars"):
                try:
                    vars_dict = store.adb_engine.get_fastboot_vars(serial=serial)
                except TypeError:
                    vars_dict = store.adb_engine.get_fastboot_vars()
            else:
                vars_dict = {}
            return {"success": True, "vars": vars_dict}
        elif action == "switch_slot":
            slot = payload.get("slot", "a")
            ok, msg = store.adb_engine.fastboot_switch_slot(slot, serial=serial) if hasattr(store.adb_engine, "fastboot_switch_slot") else (False, "Not supported")
            return {"success": ok, "message": msg}
        elif action == "reboot":
            target = payload.get("target", "system")
            ok, msg = store.adb_engine.fastboot_reboot_target(target, serial=serial) if hasattr(store.adb_engine, "fastboot_reboot_target") else (False, "Not supported")
            return {"success": ok, "message": msg}
        elif action == "wipe":
            part = payload.get("partition", "cache")
            ok, msg = store.adb_engine.fastboot_wipe_partition(part, serial=serial) if hasattr(store.adb_engine, "fastboot_wipe_partition") else (False, "Not supported")
            return {"success": ok, "message": msg}
        return {"success": False, "message": f"Unknown fastboot action: {action}"}

    @app.post("/api/screen/dpad")
    def send_dpad_key(payload: dict[str, str]):
        dpad_map = {
            "up": 19,
            "down": 20,
            "left": 21,
            "right": 22,
            "center": 23,
            "menu": 82,
            "camera": 27,
            "back": 4,
            "home": 3,
            "recent": 187,
            "power": 26,
            "volup": 24,
            "voldown": 25,
        }
        direction = payload.get("direction", "").lower()
        key = dpad_map.get(direction)
        if not key:
            raise HTTPException(status_code=400, detail=f"Invalid direction: {direction}")
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, out, err = store.adb_engine.run_shell(f"input keyevent {key}", target_serial=serial)
        return {"success": ok, "key": key}

    @app.post("/api/apps/launch")
    def launch_app(payload: dict[str, str]):
        pkg = payload.get("package", "").strip()
        if not pkg:
            raise HTTPException(status_code=400, detail="Package required")
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        cmd = f"monkey -p {shlex.quote(pkg)} -c android.intent.category.LAUNCHER 1"
        ok, out, err = store.adb_engine.run_shell(cmd, target_serial=serial)
        return {"success": ok, "message": out or err}

    @app.post("/api/tools/open_folder")
    def open_local_folder(payload: dict[str, str]):
        folder_type = payload.get("type", "backups")
        if folder_type == "backups":
            folder_path = os.path.join(DATA_DIR, "backups")
        elif folder_type == "logs":
            folder_path = os.path.join(DATA_DIR, "logs")
        elif folder_type == "models":
            folder_path = os.path.join(DATA_DIR, "models")
        else:
            folder_path = DATA_DIR
        os.makedirs(folder_path, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder_path)
        else:
            import subprocess
            subprocess.Popen(["xdg-open", folder_path])
        return {"success": True, "path": folder_path}

    @app.post("/api/tools/restart_adb")
    def restart_adb():
        store = _get_store()
        ok, msg = store.adb_engine.restart_adb_server() if hasattr(store.adb_engine, "restart_adb_server") else (False, "Not supported")
        return {"success": ok, "message": msg}

    @app.get("/api/backups")
    def list_backups():
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        backups = store.adb_engine.scan_all_device_backups(serial=serial) if hasattr(store.adb_engine, "scan_all_device_backups") else []
        return {"backups": backups, "count": len(backups)}

    @app.post("/api/backups/backup_all")
    def backup_all_apks():
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        count = store.adb_engine.backup_all_user_apks(serial=serial) if hasattr(store.adb_engine, "backup_all_user_apks") else 0
        return {"success": True, "count": count, "message": f"Successfully backed up {count} applications"}

    # ── JOURNAL & UNDO APIS ───────────────────────────────────────────────────
    @app.get("/api/journal")
    def get_journal(pending_only: bool = False):
        store = _get_store()
        cur = store.get_current_device()
        serial = cur.serial if cur else None
        muts = APP_DB.get_mutations(serial=serial, pending_only=pending_only)
        return {"mutations": muts}

    @app.post("/api/journal/undo")
    def undo_mutation(payload: dict[str, str]):
        mutation_id = payload.get("mutation_id", "")
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        ok, msg = engine.undo_mutation(mutation_id, serial=serial)
        if ok:
            APP_DB.mark_mutation_undone(mutation_id)
        return {"success": ok, "message": msg}

    # ── TERMINAL QUICK COMMAND API ────────────────────────────────────────────
    @app.post("/api/terminal/run")
    def run_terminal_command(payload: dict[str, str]):
        cmd = payload.get("command", "").strip()
        if not cmd:
            raise HTTPException(status_code=400, detail="Command required")
        store = _get_store()
        engine = store.adb_engine
        cur = store.get_current_device()
        serial = cur.serial if cur else ""
        if cmd.startswith("adb "):
            parts = shlex.split(cmd[4:])
            ok, out, err = engine.run_adb(parts, target_serial=serial)
        elif cmd.startswith("fastboot "):
            parts = shlex.split(cmd[9:])
            ok, out, err = engine.run_fastboot(parts, target_serial=serial)
        else:
            ok, out, err = engine.run_shell(cmd, target_serial=serial)
        return {"success": ok, "stdout": out, "stderr": err}

    # ── LOGS & AUDIT APIS ─────────────────────────────────────────────────────
    @app.get("/api/logs")
    def get_logs(limit: int = 150, level: str = "ALL"):
        logs = APP_DB.get_recent_logs(limit=limit, level=level)
        return {"logs": logs}

    @app.post("/api/logs/clear")
    def clear_logs():
        APP_DB.clear_logs()
        return {"success": True}

    # ── LOCAL AI BRAIN COPILOT APIS ───────────────────────────────────────────
    @app.get("/api/ai/status")
    def get_ai_status():
        store = _get_store()
        brain = getattr(store, "brain_engine", None)
        return {
            "ready": getattr(brain, "is_ready", False) if brain else False,
            "starting": getattr(brain, "is_starting", False) if brain else False,
            "status": getattr(brain, "status_msg", "Offline") if brain else "Offline",
            "model_path": getattr(brain, "model_path", "") if brain else "",
        }

    @app.post("/api/ai/toggle")
    def toggle_ai():
        store = _get_store()
        brain = getattr(store, "brain_engine", None)
        if not brain:
            raise HTTPException(status_code=500, detail="AIBrainEngine not attached")
        if brain.is_ready:
            brain.stop_server()
            return {"ready": False, "status": "Offline (RAM Freed)"}
        else:
            brain.start_server()
            return {"ready": False, "status": "Starting Gemma 4B..."}

    @app.post("/api/ai/chat")
    def chat_ai(payload: dict[str, Any]):
        message = payload.get("message", "").strip()
        confirmed = payload.get("confirmed", True)
        if not message:
            raise HTTPException(status_code=400, detail="Message required")
        store = _get_store()
        brain = getattr(store, "brain_engine", None)
        if not brain:
            raise HTTPException(status_code=500, detail="AIBrainEngine not attached")
        # Run turn with engine
        resp, action = brain.execute_copilot_turn(
            message,
            store.adb_engine,
            store,
            confirm=(lambda p: bool(confirmed))
        )
        return {"response": resp, "action": action}

    # ── SETTINGS APIS ─────────────────────────────────────────────────────────
    @app.get("/api/settings")
    def get_settings():
        return {"settings": APP_DB.get_all_config()}

    @app.post("/api/settings")
    def update_settings(payload: dict[str, Any]):
        for k, v in payload.items():
            APP_DB.set_config(k, v)
        return {"success": True}

    # ── SINGLE-PAGE WEBUI FRONTEND (INDEX.HTML & ASSETS) ─────────────────────
    @app.get("/style.css")
    def serve_css():
        css_file = os.path.join(BASE_DIR, "web", "style.css")
        if os.path.isfile(css_file):
            return FileResponse(css_file, media_type="text/css")
        return HTMLResponse("", status_code=404)

    @app.get("/index.html", response_class=HTMLResponse)
    @app.get("/", response_class=HTMLResponse)
    def serve_frontend():
        html_file = os.path.join(BASE_DIR, "web", "index.html")
        if os.path.isfile(html_file):
            with open(html_file, encoding="utf-8") as f:
                return f.read()
        return "<h1>ADB AppControl WebUI is initializing...</h1>"

    web_dir = os.path.join(BASE_DIR, "web")
    if os.path.isdir(web_dir):
        from fastapi.staticfiles import StaticFiles
        app.mount("/web", StaticFiles(directory=web_dir), name="web")
        app.mount("/static", StaticFiles(directory=web_dir), name="static")

    return app


def run_web_server(store_provider=None, host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True):
    """Starts the FastAPI WebUI server using Uvicorn and automatically launches browser."""
    import uvicorn

    # Test port availability and find open port if 8080 is occupied
    actual_port = port
    import socket
    for p in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, p)) != 0:
                actual_port = p
                break

    app = create_app(store_provider)

    url = f"http://{host}:{actual_port}"
    LOGGER.info("ADB AppControl WebUI server starting at: %s", url)
    print("\n=======================================================")
    print("  ADB AppControl Universal Edition — Modern WebUI")
    print(f"  URL: {url}")
    print("  Press Ctrl+C to stop server")
    print("=======================================================\n")

    if open_browser:
        def _open():
            time.sleep(1.0)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    config = uvicorn.Config(app=app, host=host, port=actual_port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server.run()
