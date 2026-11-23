"""
ADB AppControl Modern Web Server & REST / WebSocket Engine.
Standalone proxy re-exporting directly from appcontrol.pyw.
"""

from __future__ import annotations

import appcontrol

APP_DB = appcontrol.APP_DB
BASE_DIR = appcontrol.BASE_DIR
DATA_DIR = appcontrol.DATA_DIR
LOGGER = appcontrol.LOGGER
_device_to_dict = appcontrol._device_to_dict
create_app = appcontrol.create_app
run_web_server = appcontrol.run_web_server

__all__ = ["APP_DB", "BASE_DIR", "DATA_DIR", "LOGGER", "_device_to_dict", "create_app", "run_web_server"]
