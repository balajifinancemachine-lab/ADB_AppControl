"""
ADB AppControl Unified SQLite WAL Database Engine.
Standalone proxy re-exporting directly from appcontrol.pyw.
"""
from __future__ import annotations

import appcontrol

APP_DB = appcontrol.APP_DB
BASE_DIR = appcontrol.BASE_DIR
DATA_DIR = appcontrol.DATA_DIR
DB_PATH = getattr(appcontrol, "DB_PATH", "")
AppDatabase = appcontrol.AppDatabase
SQLiteLogHandler = appcontrol.SQLiteLogHandler

__all__ = ["APP_DB", "BASE_DIR", "DATA_DIR", "DB_PATH", "AppDatabase", "SQLiteLogHandler"]
