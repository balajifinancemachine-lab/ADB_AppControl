"""
ADB AppControl Unified SQLite WAL Database Engine.
Provides high-performance, atomic, zero-lag persistence for:
  - System logs & diagnostic events
  - Universal action audit trail
  - Mutation safety journal (reversibility & restore tracking)
  - Application settings & preferences (replaces app_config.json)
  - Device telemetry & package metadata cache (replaces JSON/CSV disk dumps)
  - Debloat rules & OEM knowledge bases
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any

# Default location for the master database
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "appcontrol.db")


class AppDatabase:
    """Thread-safe, WAL-mode SQLite database engine for ADB AppControl."""

    def __init__(self, db_path: str | None = None):
        self.db_path = os.path.normpath(os.path.abspath(db_path or DB_PATH))
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def _conn(self):
        """Yields a connection configured with WAL mode and memory temp store for max speed."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA temp_store = MEMORY;")
            conn.execute("PRAGMA cache_size = -8000;")  # 8MB cache
            with conn:
                yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _init_db(self):
        """Initializes tables and high-speed indexes."""
        with self._lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL
                );

                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    level TEXT,
                    logger TEXT,
                    message TEXT,
                    created_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_logs_created ON system_logs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_level ON system_logs(level);

                CREATE TABLE IF NOT EXISTS audit_records (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    category TEXT,
                    action TEXT,
                    target TEXT,
                    command TEXT,
                    duration_sec REAL,
                    return_code INTEGER,
                    status TEXT,
                    response TEXT,
                    error TEXT,
                    created_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_records(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_records(category);

                CREATE TABLE IF NOT EXISTS mutation_journal (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    serial TEXT,
                    action TEXT,
                    package_name TEXT,
                    undo_command TEXT,
                    label TEXT,
                    backup_dir TEXT,
                    undone INTEGER DEFAULT 0,
                    created_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_journal_serial ON mutation_journal(serial);
                CREATE INDEX IF NOT EXISTS idx_journal_undone ON mutation_journal(undone);

                CREATE TABLE IF NOT EXISTS device_cache (
                    serial TEXT PRIMARY KEY,
                    model TEXT,
                    android_version TEXT,
                    build_id TEXT,
                    battery_level INTEGER,
                    state TEXT,
                    raw_info TEXT,
                    last_seen REAL
                );

                CREATE TABLE IF NOT EXISTS package_cache (
                    serial TEXT,
                    package_name TEXT,
                    label TEXT,
                    is_system INTEGER,
                    is_disabled INTEGER,
                    is_uninstalled INTEGER,
                    apk_path TEXT,
                    version_name TEXT,
                    icon_path TEXT,
                    updated_at REAL,
                    PRIMARY KEY (serial, package_name)
                );
                CREATE INDEX IF NOT EXISTS idx_pkg_serial ON package_cache(serial);

                CREATE TABLE IF NOT EXISTS debloat_rules (
                    package_name TEXT PRIMARY KEY,
                    label TEXT,
                    category TEXT,
                    risk_level TEXT,
                    description TEXT,
                    recommendation TEXT,
                    updated_at REAL
                );
            """)

    # ── CONFIGURATION (REPLACES app_config.json) ──────────────────────────────
    def get_config(self, key: str, default: Any = None) -> Any:
        with self._lock, self._conn() as conn:
            cur = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except Exception:
                return row["value"]

    def set_config(self, key: str, value: Any):
        val_str = json.dumps(value) if not isinstance(value, str) else value
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO app_config (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, val_str, time.time())
            )

    def get_all_config(self) -> dict[str, Any]:
        with self._lock, self._conn() as conn:
            cur = conn.execute("SELECT key, value FROM app_config")
            res = {}
            for row in cur.fetchall():
                try:
                    res[row["key"]] = json.loads(row["value"])
                except Exception:
                    res[row["key"]] = row["value"]
            return res

    def import_legacy_config_file(self, config_file_path: str):
        """Imports an existing JSON config file into SQLite."""
        if not os.path.isfile(config_file_path):
            return
        try:
            with open(config_file_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    self.set_config(k, v)
        except Exception:
            pass

    # ── SYSTEM LOGGING (REPLACES PLAIN TEXT LOG DISK CHURN) ───────────────────
    def log_message(self, level: str, logger: str, message: str):
        ts = time.strftime("%H:%M:%S")
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO system_logs (timestamp, level, logger, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (ts, level, logger, message, time.time())
            )
            # Prune old logs if exceeding 50,000 entries
            conn.execute(
                "DELETE FROM system_logs WHERE id IN ("
                "SELECT id FROM system_logs ORDER BY id ASC LIMIT max(0, (SELECT count(*) FROM system_logs) - 50000)"
                ")"
            )

    def get_recent_logs(self, limit: int = 200, level: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            if level and level.upper() != "ALL":
                cur = conn.execute(
                    "SELECT * FROM system_logs WHERE level = ? ORDER BY id DESC LIMIT ?",
                    (level.upper(), limit)
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM system_logs ORDER BY id DESC LIMIT ?",
                    (limit,)
                )
            rows = cur.fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_logs(self):
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM system_logs")

    # ── ACTION AUDIT RECORDS ──────────────────────────────────────────────────
    def record_audit(self, audit_dict: dict[str, Any]):
        aid = audit_dict.get("id") or f"aud_{int(time.time()*1000)}"
        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO audit_records
                (id, timestamp, category, action, target, command, duration_sec, return_code, status, response, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                aid,
                audit_dict.get("timestamp", time.strftime("%H:%M:%S")),
                audit_dict.get("category", "ADB"),
                audit_dict.get("action", ""),
                audit_dict.get("target", "Global"),
                audit_dict.get("command", ""),
                float(audit_dict.get("duration_sec", 0.0)),
                int(audit_dict.get("return_code", 0)),
                audit_dict.get("status", "SUCCESS"),
                str(audit_dict.get("response", ""))[:4000],
                str(audit_dict.get("error", ""))[:2000],
                time.time()
            ))

    def get_recent_audits(self, limit: int = 200, category: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            if category and category.upper() != "ALL":
                cur = conn.execute(
                    "SELECT * FROM audit_records WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                    (category.upper(), limit)
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM audit_records ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
            rows = cur.fetchall()
            return [dict(r) for r in reversed(rows)]

    # ── MUTATION JOURNAL (REPLACES mutation_journal.json) ─────────────────────
    def record_mutation(
        self,
        mutation_id: str,
        serial: str,
        action: str,
        package_name: str,
        undo_command: str,
        label: str = "",
        backup_dir: str = ""
    ):
        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO mutation_journal
                (id, timestamp, serial, action, package_name, undo_command, label, backup_dir, undone, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (
                mutation_id,
                time.strftime("%Y-%m-%d %H:%M:%S"),
                serial,
                action,
                package_name,
                undo_command,
                label,
                backup_dir,
                time.time()
            ))

    def mark_mutation_undone(self, mutation_id: str):
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE mutation_journal SET undone = 1 WHERE id = ?", (mutation_id,))

    def get_mutations(self, serial: str | None = None, pending_only: bool = False) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            query = "SELECT * FROM mutation_journal WHERE 1=1"
            params: list[Any] = []
            if serial:
                query += " AND serial = ?"
                params.append(serial)
            if pending_only:
                query += " AND undone = 0"
            query += " ORDER BY created_at DESC LIMIT 300"
            cur = conn.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

    def import_legacy_journal_file(self, journal_file_path: str):
        if not os.path.isfile(journal_file_path):
            return
        try:
            with open(journal_file_path, encoding="utf-8") as f:
                entries = json.load(f)
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict) and "id" in e:
                        with self._lock, self._conn() as conn:
                            conn.execute("""
                                INSERT OR IGNORE INTO mutation_journal
                                (id, timestamp, serial, action, package_name, undo_command, label, backup_dir, undone, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                e["id"],
                                e.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S")),
                                e.get("serial", ""),
                                e.get("action", "mutation"),
                                e.get("package_name", ""),
                                e.get("undo_command", ""),
                                e.get("label", ""),
                                e.get("backup_dir", ""),
                                1 if e.get("undone") else 0,
                                e.get("created_at", time.time())
                            ))
        except Exception:
            pass

    # ── DEVICE & PACKAGE CACHE ────────────────────────────────────────────────
    def save_device_telemetry(self, serial: str, model: str, version: str, build_id: str, battery: int, state: str, raw_info: dict | None = None):
        raw_str = json.dumps(raw_info or {})
        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO device_cache
                (serial, model, android_version, build_id, battery_level, state, raw_info, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (serial, model, version, build_id, battery, state, raw_str, time.time()))

    def get_cached_devices(self) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            cur = conn.execute("SELECT * FROM device_cache ORDER BY last_seen DESC")
            return [dict(r) for r in cur.fetchall()]

    def cache_packages(self, serial: str, packages: list[dict[str, Any]]):
        now = time.time()
        rows = [
            (
                serial,
                p.get("package", ""),
                p.get("label") or p.get("name", ""),
                1 if p.get("system") else 0,
                1 if p.get("disabled") else 0,
                1 if p.get("uninstalled") else 0,
                p.get("path", ""),
                p.get("version", ""),
                p.get("icon_path", ""),
                now
            )
            for p in packages if p.get("package")
        ]
        with self._lock, self._conn() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO package_cache
                (serial, package_name, label, is_system, is_disabled, is_uninstalled, apk_path, version_name, icon_path, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

    def get_cached_packages(self, serial: str) -> list[dict[str, Any]]:
        with self._lock, self._conn() as conn:
            cur = conn.execute("SELECT * FROM package_cache WHERE serial = ? ORDER BY package_name ASC", (serial,))
            results = []
            for r in cur.fetchall():
                results.append({
                    "package": r["package_name"],
                    "name": r["label"] or r["package_name"],
                    "label": r["label"] or r["package_name"],
                    "system": bool(r["is_system"]),
                    "disabled": bool(r["is_disabled"]),
                    "uninstalled": bool(r["is_uninstalled"]),
                    "path": r["apk_path"],
                    "version": r["version_name"],
                    "icon_path": r["icon_path"]
                })
            return results

    # ── DEBLOAT RULES ENGINE ──────────────────────────────────────────────────
    def import_debloat_profiles(self, profiles: list[dict[str, Any]]):
        now = time.time()
        rows = [
            (
                p.get("package", ""),
                p.get("label", ""),
                p.get("category", "Third-Party"),
                p.get("risk_level", "SAFE"),
                p.get("description", ""),
                p.get("recommendation", "Removal optional"),
                now
            )
            for p in profiles if p.get("package")
        ]
        with self._lock, self._conn() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO debloat_rules
                (package_name, label, category, risk_level, description, recommendation, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)

    def get_debloat_rule(self, pkg: str) -> dict[str, Any] | None:
        with self._lock, self._conn() as conn:
            cur = conn.execute("SELECT * FROM debloat_rules WHERE package_name = ?", (pkg,))
            row = cur.fetchone()
            return dict(row) if row else None


class SQLiteLogHandler(logging.Handler):
    """Logging handler that routes records into SQLite in WAL mode."""

    def __init__(self, db: AppDatabase):
        super().__init__()
        self.db = db

    def emit(self, record: logging.LogRecord):
        try:
            msg = record.getMessage()
            self.db.log_message(record.levelname, record.name, msg)
        except Exception:
            self.handleError(record)


# Global singleton instance
APP_DB = AppDatabase()
