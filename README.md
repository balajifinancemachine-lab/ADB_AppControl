# ADB AppControl — Universal Monolithic Edition

A single-file Windows desktop control center for Android devices over **ADB, Fastboot, Recovery/Sideload and MTP**. It packages app management, a 4-tier debloat wizard, an unbrick/rescue suite, permissions and process tooling, screen capture/mirroring, an APK installer, a live terminal plus a full action audit trail — in one dependency-light Python GUI (`appcontrol.pyw`).

---

## Overview

| | |
|---|---|
| **Sole application file** | `appcontrol.pyw` (~9.8k lines, all-inclusive engine + views + SQLite + CLI suites) |
| **Windows launcher** | `run_app.bat` (picks a verified interpreter, supports `--test`, `--audit`, `--organize`, `--heal`) |
| **GUI Layout** | **3-Panel Ergonomic Architecture**: Left Navigation Sidebar, Center Comfortable Main View, and Right Collapsible Live Activity Console |
| **Right Live Panel** | Real-time command audit stream, execution timings, task progress bar, log filter, copy/clear, and interactive mini-terminal |
| **GUI toolkit** | `customtkinter` 6 + Pillow (Tk-based, dark/light themes) |
| **State model** | `AppStateStore` — reactive store with lazy per-view refresh, so inactive tabs cost nothing |
| **Device Storage** | `DeviceDatabase` — per-device SQLite in WAL mode (`device.db`) with sub-millisecond queries & auto-healing |
| **UI Rendering** | Continuous smooth-scrolling (`CTkScrollableFrame`) with progressive chunked rendering (zero pagination lag) |
| **Concurrency** | Daemon background threads per long job; every ADB call is audited |

The app is designed for **zero UI freezing**: shell work happens off the Tk thread, device scans use single-trip compound `adb shell` commands, and results are marshalled back with `safe_after()`.

---

## Features

### ⚡ Per-Device High Performance Database (`device.db`)
* **Dedicated SQLite WAL Storage**: Each connected device automatically provisions an isolated SQLite database at `data/cache/device/<Model_Serial>/device.db`.
* **Zero UI Lag**: Configured with `PRAGMA journal_mode = WAL;`, `PRAGMA synchronous = NORMAL;`, and `PRAGMA temp_store = MEMORY;` allowing non-blocking concurrent reads and background syncs.
* **Sub-Millisecond Query Latency**: Scans 350+ installed applications and returns fully hydrated package records in under **0.20 ms** (compared to several seconds over raw ADB shell). Batch atomic syncing completes in ~**0.59 ms**.
* **Indexed Queries**: Dedicated indexes for `type`, `enabled`, `uninstalled`, `is_bloat`, and package `name` for instantaneous live filtering and search.
* **Auto-Healing & Recovery**: Proactively validates database integrity via `PRAGMA integrity_check;`, vacuums overhead, cleans orphaned WAL journals, and cleanly re-initializes fresh storage with zero data loss if disk corruption or abrupt disconnection occurs.
* **Telemetry & Audit Persistence**: Persists hardware specs, display metrics, battery states, custom labels, and an immutable action audit trail across disconnects.

### 📱 Applications (Continuous Smooth Scrolling & Preset Lists)
* **No Pagination**: Replaced rigid pagination buttons with continuous, natural high-performance scrolling inside CustomTkinter scrollable frames.
* **Progressive Non-Blocking Micro-Batches**: Renders hundreds of packages in micro-batches (15 rows per slice via Tk event loops), keeping the interface silky smooth and 100% responsive during rendering.
* **💾 Save & 📂 Load Selection Preset Lists**:
  * **Save Selections**: Save any active checkbox selection (or prompt to save all currently filtered apps, e.g. 96 uninstalled system apps) into a clean, human-readable `.txt`, `.adac`, or `.json` list with friendly package names and metadata.
  * **Load Selections**: Import any `.txt`, `.adac`, `.json`, or exported `.csv` package list. ADB AppControl automatically parses package identifiers, strips comments, handles UTF-8 BOM (`\ufeff`) from Windows Notepad, matches apps against the connected device, checks checkboxes, and switches view to **"Selected"** for instant batch execution.
  * **Smart Directory Fallback**: Intelligently checks device-specific preset folders (`data/presets/<Model_Serial>/`) first; if empty, smoothly opens the shared root `data/presets/` folder so users never see an empty directory.
  * **Repeat Actions Without Tedious Re-selection**: For example, easily export a list of currently uninstalled packages to restore/enable them today, and import that exact same `.txt` list anytime in the future to batch disable or uninstall them in one click.
  * **Replace or Add Mode**: When loading a list while items are already selected, choose whether to cleanly replace or merge with existing selections.
* **Ergonomic 2-Row Action Bar**:
  * **Row 1 (Selection & Presets)**: `☑ All`, `☐ None`, `⇄ Invert`, `💾 Save List`, `📂 Load List`, `📤 Export`, and live counter `Total: X | Showing: Y | Selected: Z`.
  * **Row 2 (Batch Actions on Selected)**: `🔄 Restore`, `✅ Enable`, `⛔ Disable`, `🗑 Uninstall`, `⏹ Stop`, `👁 Hide`, `⚡ Auto-Perms`, `🧹 Clear Data`, `💾 Save APKs`.
* **Full Package Inventory**: System/user, enabled/disabled, uninstalled-but-present detection via compound shell calls and indexed local cache fallback.
* **Per-App Actions**: Disable, enable, hide, unhide, force-stop, clear cache, clear data, compile (`speed`/`speed-profile`), launch, open system settings, uninstall (`--user 0`, reversible), restore system app (`install-existing`).
* **APK Backup**: High-speed backup to `data/backups/<Model_Serial>/<package>/` with timestamped APK archiving.
* **Structured Package Details**: Version names/codes, UID, SDK levels, installer, permissions, exported activities, and one-click JSON/CSV/HTML exports.
* **Device Specs**: Active A/B boot slot, memory page size (`4 KB` vs `16 KB` alignment), battery health, and temperature.

### 🧹 Debloat Wizard
* Four risk tiers — **Basic**, **Safe**, **Aggressive (medium)**, **Maximum** — with built-in signatures for Facebook/Meta, Amazon, Microsoft, Netflix, Samsung, Xiaomi/MIUI, Oppo/Realme/Vivo, Huawei and Google apps.
* OEM presets: *All Safe Bloatware*, *Samsung OneUI Clean*, *Xiaomi MIUI/HyperOS Clean*, *Oppo/Realme/Vivo Clean*, *Google & 3rd-Party Bloat*.
* Loads external presets from `data/presets/*.json` and `.adac` package lists (`tools/adb/base.en.adac`, `data/presets/base.en.adac`).
* Applies actions with per-package status, and every operation is recorded in the audit log.
* **♻️ Restore All** re-enables every disabled (still installed) package in one action — the documented undo path after a disable-based debloat. Restores use `cmd package install-existing --user 0` + `pm enable --user 0`.

### 🛠 Rescue & Unbrick
* **Bootloop catch & fix** — waits for `adb wait-for-device` during early boot, then: restore/re-enable core packages (SystemUI, Settings, Play services…), force Safe Mode, strip Magisk modules, or disable RescueParty and trim caches.
* **Fastboot suite** — `getvar all`, slot switching (`--set-active`), flash boot/recovery/vbmeta (with `--disable-verity`), temporary `fastboot boot`, erase partition, factory reset (`-w`), reboot to system/bootloader/fastbootd/recovery, OEM unlock.
* **Sideload** — flash OTA/rescue ZIPs via `adb sideload`.
* **MTP/USB diagnostics** — detects portable MTP devices plus **Qualcomm EDL 9008**, **MediaTek Preloader/BROM**, Odin and fastboot USB interfaces even when ADB is dead; opens the OS file manager at the MTP root; can switch USB function (`mtp,adb`, `ptp,adb`, `rndis,adb`, `midi`, `none`).

### ⚡ Process Manager (Continuous Smooth Scrolling)
* **Continuous Scroll View**: No page toggles; all active processes render in a unified scrollable list with dynamic filtering.
* **Adaptive Column Header Parsing**: Automatically detects device `ps` formats (`PID`, `USER`, `RSS`, `NAME`) across Android 8 through 15.
* **Live Memory Overview**: Real-time RAM statistics, swap metrics, and process termination with truthful status confirmation.

### 🔐 Permissions
* Scan which packages hold (or were denied) a given dangerous permission.
* Grant/revoke per app, with automatic **AppOps fallback** when `pm grant` is refused (`CAMERA`, location, `READ_SMS`, `MANAGE_EXTERNAL_STORAGE`, notification access, …).
* Bulk auto-grant for a single package (and for every selected app) that only attempts **runtime/dangerous** permissions — signature, privileged and normal permissions can never be granted by `pm grant`, so they are filtered out instead of producing hundreds of `SecurityException` failures. All grants for one package run in a single adb shell session, followed by a batched AppOps re-assertion.

### 🎮 Screen & Remote
* Screenshot → file and/or **Windows clipboard**.
* Screen recording (5–180 s) pulled to `video/`; the capture is verified (remote size + pulled bytes), so an empty recording such as `INVALID_LAYER_STACK` on a sleeping display is reported as a failure instead of a fake success.
* **Scrcpy** mirroring with bitrate, max-size, screen-off, stay-awake and **mute** controls. The binary is resolved from the **latest GitHub release** (architecture-aware, with pinned fallbacks down to v3.1) on first use.
* Display power control: `cmd display power-off/power-on 0` on Android 15+, `input keyevent 223/224` on older builds.
* Display scaling: resolution/density override and reset.
* Input injection: keyevents, tap, swipe, text; device clipboard read/write.

### 📦 Install & MTP/Files
* Install single APK, split APK sets (`install-multiple`), or `.xapk/.apks/.apkm` bundles with `-r -d -g -t` options.
* Local APK inspection (package, version, min/target SDK, permissions) via `pyaxmlparser`, with a pure-Python `AndroidManifest.xml` string scanner fallback.
* Push/pull files and folder shortcuts, plus engine-level `push_file`/`pull_file` with absolute-path validation and a 300 s transfer timeout for large payloads.

### 💻 ADB/Fastboot Terminal
* Interactive command console with history/output pane and an **mDNS** quick command (`adb mdns services`) for wireless-debugging discovery.
* Live **logcat** streaming with start/stop and filters, plus a one-click **Logcat snapshot** that writes the last 2 000 lines to `data/logs/<Model_Serial>/logcat_<ts>.txt`.

### ⚙️ Settings & Tools
* Reboot menu (system, recovery, bootloader, sideload, power off) with confirmations.
* Fastboot tools, ADB daemon restart, custom `adb` executable path.
* Theme (dark/light), accent, silent mode, auto-detect, icon size, **startup PIN lock** (SHA-256 hash stored in config), APK backup/restore manager with batch backup, and one-click access to `data/backups/`, `data/exports/`, `data/presets/`, `data/screenshots/`, `data/logs/`.
* **Multi-device safety**: with more than one device attached, `run_adb` refuses any command that does not name a target serial instead of silently acting on the first device.
* **Automatic updates on start** — a throttled background `AutoUpdater` checks PyPI (`customtkinter`, `Pillow`, `pyaxmlparser`), Google's platform-tools repository index and the scrcpy GitHub release, then upgrades each component in place. It never blocks the UI, never fails fatally, and can be toggled or triggered manually with **🔄 Check Now**.

---

## Requirements

* **Windows 10/11** (primary target). Linux/macOS paths exist for `adb`/`scrcpy` discovery, `lsusb` scanning and `xdg-open`, but are not the tested configuration.
* **Python 3.10+** — verified here on **3.15.2**.
* `customtkinter>=6.0.0`, `pillow>=12.3.0` (required), `pyaxmlparser>=0.3.31` (optional, better APK parsing) — kept current automatically after launch.
* Android **platform-tools** (`adb`, `fastboot`) and optionally **scrcpy** — the app downloads official Google platform-tools on demand, and resolves the newest scrcpy release from the GitHub API (falling back through pinned v5.0.1 → v3.1 builds, with `win64`/`win32`/`winarm64` assets) when mirroring is first used.
* Dependencies are kept current automatically (24 h throttle). `requirements.txt` uses minimum versions (`>=`) so a manual `pip install -r` does not fight the updater.

---

## Install & run

```bat
cd /d C:\path\to\ADB_AppControl

python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

run_app.bat
```

Alternative launch paths & built-in CLI suites:

```bat
.venv\Scripts\pythonw.exe appcontrol.pyw          :: start GUI without a console
run_app.bat --test                               :: run built-in 15-test unit verification suite
run_app.bat --audit                              :: run deep audit on connected device
run_app.bat --organize                           :: trigger automated storage organization & self-heal
run_app.bat --heal                               :: rebuild/migrate the data/+tools/ layout and repair stale paths
run_app.bat --repair                             :: re-download missing adb/scrcpy tools (user data untouched)
run_app.bat --cleanup                            :: keep the newest 20 logcat/screenshot/video files per device
run_app.bat --verify-device                      :: read-only device + layout checks (add --write for screenshot/logcat)
```

`run_app.bat` prefers `.venv\Scripts\pythonw.exe` for silent GUI launches, and dynamically falls back to console python when CLI flags (`--test`, `--audit`, `--organize`, `--heal`, `--repair`, `--cleanup`, `--verify-device`) are provided. Only one GUI copy can run at a time (a lock in `data/config/` stops a second instance from rewriting the config or undo journal).

### First run

1. The `data/` and `tools/` folder contract is created automatically (`data/config`, `data/logs`, `data/cache`, `data/backups`, `data/exports`, `data/presets`, `data/screenshots`, `data/video`, `data/downloads`, plus `tools/adb`, `tools/scrcpy`, `tools/llama`, `tools/models`) together with a default config. Any folder from an older layout found beside the app is migrated into place on first launch.
2. Missing `customtkinter`/`Pillow` are pip-installed automatically before the GUI loads.
3. The startup scan calls `ensure_environment()`: runs storage self-healing/organization, verifies platform-tools, and extracts `adb/` if needed.
4. Scrcpy is fetched only when you first press **Launch Scrcpy** (Windows).
5. Connect a device with USB debugging enabled and accept the RSA prompt.

---

## Project layout

```
ADB_AppControl/
├── appcontrol.pyw            # 100% all-inclusive monolithic application (engine, views, SQLite, CLI suites)
├── run_app.bat               # verified-interpreter portable Windows launcher
├── build_release.bat         # PyInstaller one-directory release build
├── requirements.txt          # pinned runtime dependencies
├── tools/                    # everything the app runs (ships with the build)
│   ├── adb/                  # platform-tools (adb, fastboot) + optional .adac
│   ├── scrcpy/               # scrcpy binaries (auto-resolved from GitHub)
│   ├── llama/                # local llama-server runtime for the AI Brain
│   └── models/               # optional GGUF model drop-in folder
└── data/                     # everything the app writes (never shipped)
    ├── config/app_config.json  # persisted settings (auto-created, self-healing)
    ├── config/mutation_journal.json  # undo journal
    ├── presets/              # debloat presets (*.json, *.adac)
    ├── cache/                # icons, APK and device-info caches
    │   └── device/           # per-device folders (<model>_<serial>/device.db [WAL mode])
    ├── backups/              # device-specific APK backups (<model>_<serial>/<pkg>/...) + backup_info.json (size + SHA-256)
    ├── downloads/            # transient tool archives
    ├── exports/              # device-specific JSON/CSV/HTML reports (<model>_<serial>/...)
    ├── logs/appcontrol.log   # rotating application log + device-specific subfolders
    ├── screenshots/          # device-specific screen captures (<model>_<serial>/...)
    ├── video/                # device-specific screen recordings (<model>_<serial>/...)
    ├── quarantine/           # duplicate files parked by the layout migration (nothing is deleted)
    └── brain.db              # AI Brain WAL database
```

The data root is resolved dynamically: `data/` beside the app when that folder is writable, otherwise a per-user folder (`%LOCALAPPDATA%\ADB_AppControl\data` on Windows). `python appcontrol.pyw --heal` re-runs the folder contract, migrates legacy layouts and repairs stale absolute paths without deleting anything.

### Code map (single module)

| Class | Responsibility |
|---|---|
| `DeviceDatabase` | Per-device SQLite storage in WAL mode (`device.db`), fast indexing, specs caching, and auto-healing |
| `BrainDatabase` | Universal AI Brain SQLite storage in WAL mode (`brain.db`): continuous action learning, habit patterns, and diagnostic logs |
| `AutoHealAgent` | Self-healing autonomous agent: intercepts runtime exceptions, repairs ADB/SQLite/Tkinter faults, and maintains 100% uptime |
| `AIBrainEngine` | Managed background `llama-server.exe` process for local Gemma 4B inference, action execution, and intent resolution |
| `AIBrainView` | Ergonomic interactive Copilot UI: chat history, quick action chips, learned habits notebook, and diagnostic audit logs |
| `LiveActivityPanel` | Real-time Right Panel: live ADB command stream, progress bar, timings, log filters, and interactive mini-terminal |
| `ADBEngine` | ADB/Fastboot/Recovery/MTP operations, package listing, telemetry, APK install/backup, wireless ADB |
| `AppStateStore` | Reactive state, device/app cache, lazy view updates, engine lifetime |
| `ApplicationsView` | Non-blocking continuous scrollable list (`CTkScrollableFrame`), live count, batch actions |
| `DebloatView` | 4-tier debloat wizard, OEM presets, interactive package picker, restore-all |
| `ProcessView` | Non-blocking continuous process viewer, RAM usage bars, kill actions |
| `PermissionsView` | Permission inspector, AppOps fallbacks, bulk grant/revoke |
| `RescueView` | Bootloop rescue, fastboot tools, sideload, EDL/MTP recovery |
| `ScreenView` | Scrcpy mirroring, remote screenshot/recording, input injection |
| `InstallView` | Drag-and-drop APK, split APK and XAPK bundle installer |
| `ConsoleView` | Interactive terminal console, live logcat streaming & snapshot |
| `SettingsView` | Theme/accent, PIN lock, backup manager, auto-updater controls |
| `ADBAppControlMain` | Window shell, navigation, header/footer, scan orchestration |
| `DebloatDatabase` | Bloat signatures, risk tiers, OEM presets, `.adac`/JSON parsing, label humanising |
| `AuditLogger` / `ActionAuditRecord` | Thread-safe action → response → result audit ring buffer (1500 records) and export |
| `DataExporter` | Device-routed JSON, CSV, HTML and text report writers |
| `IconManager` | Cached letter badges + real icon extraction from APKs |
| `AppConfig` | Dict/attribute hybrid config with defaults and PIN verification |
| `AutoUpdater` | Automated in-place updater for PyPI deps, Google platform-tools, and scrcpy |

---

## Configuration (`data/config/app_config.json`)

| Key | Default | Meaning |
|---|---|---|
| `theme` | `"dark"` | `dark` / `light` appearance |
| `accent` | `"blue"` | customtkinter colour theme |
| `silent_mode` | `false` | Skip confirmation prompts |
| `show_icons` | `true` | Render app icons in lists |
| `icon_size` | `24` | 20 / 24 / 28 / 32 |
| `auto_refresh` | `true` | Poll for USB/Wi-Fi/Fastboot device changes |
| `adb_path` | `""` | Custom `adb` executable path |
| `wireless_history` | `[]` | Recent `ip:port` wireless targets (max 15) |
| `last_device` | `""` | Last used serial |
| `sort_by` / `sort_reverse` | `"name"` / `false` | Package list ordering |
| `key_protect_hash` | `""` | SHA-256 of the startup PIN (empty = no lock) |
| `app_labels` | `{}` | User-defined package → display-name overrides |
| `auto_update` | `true` | Check PyPI / Google / scrcpy for upgrades on start |
| `update_interval_h` | `24` | Minimum hours between automatic checks |
| `last_update_check` | `0` | Epoch seconds of the last successful check |
| `platform_tools_index_seen` | `""` | Last Google index revision fetched (stops repeat downloads when the ZIP lags the index) |

Unknown or missing keys fall back to defaults, so a partially corrupted file will not block startup.

---

## Debloat tiers

| Tier | Risk | Scope |
|---|---|---|
| 🟢 Basic | Very low | Carriers, Facebook/Meta, Amazon, Microsoft, common third-party bloat |
| 🟡 Safe | Low | Non-essential OEM duplicates (Samsung, Xiaomi, Oppo, Vivo, Huawei) |
| 🟠 Aggressive | Medium | Analytics, assistants, cloud backup, optional vendor tools |
| 🔴 Maximum | High | Core vendor apps and heavy services — review each package |

Debloat operations use `pm uninstall --user 0` (reversible with `cmd package install-existing <pkg>`), `pm disable-user`, or `pm hide`. Prefer **disable** when unsure.

---

## Logs, audit trail & exports

* `data/logs/appcontrol.log` — rotating operational log (all subprocess results, timings, errors).
* In-app audit trail — every action stores command, target, return code, duration, response preview and status; exportable to JSON via `AuditLogger.export_audit_log()` (e.g. `data/exports/audit_*.json`).
* Device/app snapshots — `data/exports/device_<serial>_<ts>.json` and `data/exports/apps_<serial>_<ts>.csv`, written automatically after scans.
* HTML inventory reports via `DataExporter.export_html()`.

---

## Safety notes

* **Flashing, erasing and factory reset are destructive** and can hard-brick a device. Verify the image and partition, and keep USB connected.
* **Maximum** debloat and OEM-unlock commands can break system updates or safety features.
* `--user 0` uninstalls are recoverable; a full `pm uninstall` is not.
* The startup PIN is a convenience lock (unsalted SHA-256 in a local JSON file), **not** encryption — anyone with file access can bypass it.
* Only use this on devices you own or are authorised to service.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Double-clicking does nothing | A stale `.venv` is the usual cause. Rebuild it: `rmdir /s /q .venv` then `python -m venv .venv` and `pip install -r requirements.txt`. `run_app.bat` now skips a venv that cannot run. |
| No window, no error | Run `.venv\Scripts\python.exe appcontrol.pyw` in a terminal to see the traceback; fatal startup errors also raise a dialog and log to `data/logs/appcontrol.log`. |
| `device unauthorized` | Accept the "Allow USB debugging" prompt on the phone; revoke/repair USB debugging authorisations if it never appears. |
| `no devices/emulators found` | Enable Developer options → USB debugging, try another cable/port, then **Settings → Restart ADB Daemon**. |
| Device only in Fastboot | The UI switches to **Rescue & Unbrick** automatically; use `Fastboot Getvar All` first. |
| Wireless ADB fails | Android 11+ needs both ports: `pair` with the 6-digit code, then `connect` to the debugging port (not the pairing port). |
| Scrcpy missing | Press **Launch Scrcpy** (auto-download on Windows) or drop a scrcpy build into `scrcpy/`. |
| Black screen / bootloop after debloat | **Rescue → Bootloop Catch & Fix → restore_core** re-enables SystemUI, Settings and Play services, then reboot. |

---

## Verification & development

```bat
:: syntax check
.venv\Scripts\python.exe -m py_compile appcontrol.pyw

:: run built-in self-test suite (0 external test dependencies required)
run_app.bat --test
```

It flags duplicate/overridden methods, unreachable code, bare `except`, exception variables captured by closures, missing subprocess timeouts, undefined `self` methods/attributes, config keys missing from defaults, dead functions, unquoted shell interpolation, loop-captured lambdas, mutable default arguments, duplicate dict keys, `return`/`break`/`continue` inside `finally`, `open()` without a context manager, `is`/`== None` comparisons, `assert`-based validation and TODO markers.

UI smoke test (no device required):

```python
import appcontrol
app = appcontrol.ADBAppControlMain()
for page in app.views:
    app._switch_page(page)          # exercises lazy view activation
app.store.shutdown(); app.destroy()
```

### Live device verification

Exercised on a Samsung **SM-A045F (Android 14 / SDK 34, adb shell uid 2000 — no root)** with the built-in deep audit:

```bat
run_app.bat --audit
```

**Result: 111 PASS, 0 FAIL, 1 LIMIT.** The single limit is `adb install` over a Samsung system app (`INSTALL_FAILED_REJECTED_BY_BUILDTYPE`) — a platform policy, not an application defect.

| Area | Coverage |
|---|---|
| Discovery | adb/fastboot/scrcpy resolution, device poll, ADB + fastboot scan, Windows USB/MTP/EDL bus scan |
| Telemetry | full props, specs, RAM, storage, battery, display scaling, process list, combined telemetry, Wi-Fi IP |
| Packages | full inventory (358 packages), system/user split, disabled detection, structured details, APK backup + inspection |
| Debloat | tier sizes, OEM presets, installed-package matching, bloat lookup, label humanising, preset parsing |
| App actions | disable→enable, force-stop, hide→unhide, clear cache, compile, restore, companion install (then removed) |
| Permissions | CAMERA scan (38 holders), revoke→grant with state restored |
| Media | screenshot (valid PNG), 5 s screen recording (valid MP4), key/tap/swipe/text injection, clipboard read/write, app-settings + developer-options intents |
| Display | density/size idempotency, dark-mode toggle and restore, animation scale, stay-awake and restore |
| Files | mkdir, list, chmod, rename, delete on `/sdcard`, all self-cleaning |
| Process/logs | memory trim, truthful kill refusal, logcat clear + 3 s live stream (400+ lines) |
| Store/exports | reactive store batch update, JSON/CSV/HTML export, auto device snapshot, audit export |
| Hardening | metacharacter paths, command-substitution injection, invalid density/size/chmod/USB/slot/compile inputs, protected deletes, missing APKs, heterogeneous CSV, corrupt-config recovery, permission-scan cache |
| Upgrades | scrcpy release resolution (API + fallbacks), launch-option validation (size 240–4320, bitrate, fps 1–240), screen off→on→keyguard restore, logcat snapshot (216 lines written), push→pull round-trip byte-identical, 404/bad-path guards, mDNS listing, restore-all, batch APK backup into a temp dir, empty-recording no longer reported as success (111 PASS / 0 FAIL) |
| Auto-update | live upgrades — Pillow 12.3.0 → 13.0.0, platform-tools 35.0.2 → 37.0.1, scrcpy 2.4 → 5.0.1; second run all up-to-date in 0.6 s; index/ZIP divergence suppressed; 24 h throttle persisted to config; Settings checkbox + **Check Now** construct correctly in a full GUI smoke test; all seven scrcpy launch flags re-confirmed present in 5.0.1 |
| Static audit | two AST passes over ~7.9k lines: 0 duplicate real methods, 0 unreachable blocks, 0 bare excepts, 0 exception vars captured by closures, 0 subprocess calls without a timeout, 0 undefined `self` methods/attributes, 0 config keys missing from defaults, 0 unreferenced functions, 0 mutable defaults, 0 duplicate dict keys, 0 `return` inside `finally`, 0 files opened outside a `with`; 1 loop-captured lambda and 28 shell interpolations reviewed and fixed/validated |

Every mutation is reversible and was restored; the companion APK installed during the test was uninstalled afterwards.

**Not exercisable without rebooting or a second transport:** fastboot flash/slot/erase/factory-reset, sideload, bootloop rescue, reboot/power-off, wireless pairing (`adb pair`/`tcpip`), USB function switching, scrcpy mirroring (GUI), and EDL/Preloader recovery.

---

## Robustness hardening

Every device-shell interaction now follows one rule set:

* **Never interpolate untrusted text into a shell string.** Package names and remote paths go through `shlex.quote`; typed text keeps spaces (`%s` for `input text`) while quotes and metacharacters are escaped. Verified on-device: a path containing `$(touch …)` creates no file.
* **Validate before executing.** Display size (`WxH`), density (2–4 digits), animation scale (0–10), chmod mode (octal), USB function (allowlist), boot slot (`a`/`b`), partition (alphanumeric) and compile mode (allowlist) are checked and rejected with a clear message instead of reaching the device.
* **Guard destructive operations.** `delete_remote` refuses root mounts and `/sdcard`, `/data`, `/system`, `/storage/emulated`; `install_apks` pre-checks every file; uninstall fallbacks stay on `--user 0`.
* **Treat archives as hostile.** One safe extractor rejects traversal, absolute and drive-letter members (zip-slip) for platform-tools, scrcpy and XAPK bundles.
* **Make state durable.** Config saves are atomic (`fsync` + `os.replace`), corrupt configs are backed up rather than discarded, and CSV/JSON/HTML exporters tolerate heterogeneous or empty data.
* **Avoid needless work and collisions.** Permission scans are cached per device/permission for 90 s (invalidated on grant/revoke), and capture/export temp files use millisecond timestamps.

---

## Audit log — fixes applied

Findings from a static + runtime audit of the application, and what changed:

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | **Critical** | `.venv` was created for a Python 3.14 install that no longer exists (and an old `Downloads\…` path), so `run_app.bat` launched a dead interpreter and the app never opened. | Rebuilt `.venv` on Python 3.15.2 with pinned deps; `run_app.bat` now validates the interpreter and falls back to system Python. |
| 2 | **High** | `DataExporter.export_html()` referenced `html.escape` although `html` was never imported — every HTML export failed. | Added `import html`. |
| 3 | **High** | `ADBEngine.send_key` annotated `Union[str, int]` without importing `Union` — raises `NameError` at import on Python < 3.14 (3.14+ only survives because annotations became lazy). | Added `Union` to the `typing` import. |
| 4 | Medium | Two Tk callbacks captured the `except … as e` variable; Python deletes it when the block exits, so the error dialog/status update died with `NameError` (invisible, since the app runs windowless). | Bind the message into the lambda default (`lambda msg=…`). |
| 5 | Low | Dead imports (`platform`, `as_completed`, `tk`, `ImageTk`, `ImageFont`). | Removed; pyflakes is clean. |
| 6 | Low | Leftover `"test_key": "test_val"` in shipped config. | Removed from `config/app_config.json`. |
| 7 | Low | Fatal startup errors were only logged, leaving a windowless app that silently exited. | `pythonw` launch paths now show a message box with the error and log location. |
| 8 | Low | Dependencies were implicit (auto-pip at runtime) with no manifest. | Added pinned `requirements.txt`. |
| 9 | **High** | Permission scanner returned nothing on Android 14: it required a `requested permissions:` label that Samsung/OEM dumps omit (this dump had 0 such blocks but 45 `CAMERA: granted=true` lines). | Parses `perm: granted=true/false` per package section; now finds all 38 CAMERA holders on the test device. |
| 10 | Medium | Package details showed `uid=N/A` and `installer=null` (no `userId=` line on Samsung; `installerPackageName=null` for preinstalled apps). | Falls back to `appId=`, normalises null installers, uses `timeStamp=` for first install. |
| 11 | Medium | Clipboard read returned mojibake (`"No itemsat comandroidserverclipboard…"`) from the parcel fallback. | Normalises punctuation before deciding, rejects service stack traces, returns empty for an empty clipboard. |
| 12 | Medium | `kill_process` always reported `Terminated …`, even when the shell user was denied. | Verifies the PID is gone, retries via `force-stop`, and reports the real outcome. |
| 13 | Medium | `trim_all_memory` used `cmd activity trim-memory`, which does not exist on Android 14 (`Unknown command`). | Uses `am kill-all` + `pm trim-caches` and reports the actual result. |
| 14 | Medium | `pm hide`/`pm unhide` surfaced raw `SecurityException` dumps (they need root on Android 10+). | Falls back to `disable-user`/`enable` and explains the substitution. |
| 15 | Low | Install failures showed only `Performing Streamed Install`, hiding adb's actual reason. | Reports combined stdout/stderr including `INSTALL_FAILED_*`; companion install prints a clean success message. |
| 16 | Low | Unreachable second `return` in `power_off`. | Removed. |
| 17 | **High** | Device-shell commands interpolated raw values (package names, paths, typed text, display/chmod/USB arguments), so a crafted preset or clipboard string could inject commands. | All package/path/text arguments are quoted; numeric/enumerated inputs are validated against allowlists. On-device test confirms `$(touch …)` executes nothing. |
| 18 | **High** | Archive extraction trusted member paths (zip-slip) for platform-tools, scrcpy and XAPK bundles. | Shared `_extract_zip_safely()` rejects `..`, absolute and drive-letter entries. |
| 19 | Medium | Config writes were non-atomic and a corrupt file was silently replaced by defaults. | Temp file + `fsync` + `os.replace`; corrupt files preserved as `app_config.json.corrupt-<ts>.json`. |
| 20 | Medium | The file explorer could not list `/sdcard` — the symlink produced a single entry. | Lists `path/.` first so symlinked roots resolve to their contents. |
| 21 | Medium | CSV export used only the first row's keys, losing or raising on heterogeneous records. | Key union across rows with `extrasaction='ignore'`. |
| 22 | Medium | Every permission query re-ran a 6–7 s full `dumpsys package`. | 90 s per-device/permission cache, invalidated on grant/revoke (2.5 s → 0.0 s measured). |
| 23 | Low | Screenshot/recording temp files used fixed remote names and could collide. | Millisecond-stamped remote temp names. |
| 24 | Low | `delete_remote` guarded only five exact paths; startup directory creation could crash; missing APKs went to adb first. | Expanded protected-path guard, per-directory error logging, pre-flight file checks. |
| 25 | Low | Logcat reader processes were terminated without being reaped. | `wait(timeout=2)` then `kill()` fallback. |
| 26 | **High** | Screen recording reported “Video recorded successfully” even when `screenrecord` failed and a 0-byte file was pulled — a sleeping display returns `INVALID_LAYER_STACK` (rc=218). Observed live on the test device. | Remote file size and pulled byte count are verified; empty files are deleted and the real error (with a “wake the display” hint) is surfaced. Re-verified: 5 s capture → 135 KB valid MP4. |
| 27 | Medium | The scrcpy downloader was pinned to v3.1, so new installs could never get current builds or the right architecture. | Resolves the latest GitHub release at download time, picks `win64`/`win32`/`winarm64`, and falls back through a pinned v5.0.1 → v3.1 list (verified live: newest asset = v5.0.1). Scrcpy arguments are now built and validated in `ADBEngine.launch_scrcpy` instead of the view. |
| 28 | Medium | With several devices attached, a command without `-s` could run against the wrong device. | `run_adb` refuses target-less commands when more than one device is online. |
| 29 | Medium | Debloat restore omitted `--user 0` and there was no bulk undo after a disable run. | `install-existing --user 0` + `pm enable --user 0`, plus a **Restore All** action that re-enables every disabled package. |
| 30 | Low | Batch APK backup, logcat snapshots and file push/pull had no engine API (only ad-hoc view code). | Added `backup_all_user_apks`, `save_logcat_dump`, `push_file`, `pull_file`, `list_mdns_services`, `set_screen_power`, `scrcpy_version`; UI wired to each. |
| 31 | Medium | Nothing ever upgraded what the app depends on: scrcpy stayed at 2.4, platform-tools at 35.0.2 and Pillow at 12.3.0 after install, even though newer releases existed. | New `AutoUpdater` resolves PyPI package versions, Google's platform-tools revision and the scrcpy GitHub tag, then upgrades each in place from a background thread at startup (throttled, toggleable, with a Settings **Check Now**). Verified live: all three components upgraded. |
| 32 | Medium | Google's repository index can advertise a newer platform-tools revision than the published ZIP actually contains (index 37.0.3 vs ZIP 37.0.1), which would re-download ~10 MB on every check forever. | `platform_tools_index_seen` records the index revision already fetched, the real revision is re-read after extraction, and the row reports “index lists X, ZIP ships Y”. Verified: run 2 skips the download. |
| 33 | Low | The update-failure label captured `e` from an `except` block, so it would have raised `NameError` instead of showing the error (same bug class as #4). | Bound into a lambda default; pyflakes clean. |
| 34 | Medium | The backup “Restore” button deferred its result dialog with `self.after(0, lambda: … res …)` inside the row loop, so every deferred callback read the **last** row's result. | Bound the loop value (`lambda res=res:`); each restore now reports its own outcome. |
| 35 | Medium | `send_key` interpolated its argument straight into `input keyevent <value>`, so a name containing shell metacharacters could inject a command. | Accepts only digits or an identifier-shaped key name; anything else is rejected before adb runs. |
| 36 | Medium | The packaged-app “Start” button ran `am start -n {component}` with a component string parsed from device `dumpsys` output, unquoted. | New `start_activity()` validates `pkg/cls` and passes it through `shlex.quote`. |
| 37 | Low | `open_app_settings` concatenated a raw package name into an intent URI. | The whole `package:` URI is now shell-quoted. |
| 38 | Low | XAPK/OBB install built the remote OBB directory and filename from archive contents without validation. | OBB filenames are restricted to `[A-Za-z0-9_.-]` (unsafe names are skipped and reported) and the remote directory is quoted. |
| 39 | Low | The process “Kill” action discarded the engine's result, so a refused kill looked identical to a successful one. | The outcome is shown in a dialog and the list refreshes; `trigger_global_refresh` no longer assumes its callback exists. |
| 40 | Low | Several device-critical handlers (`manifest.json` parsing for OBB push, icon-cache scanning, `lsusb` probing, post-update binary re-resolution, index-revision persistence) swallowed errors with bare `pass`. | Each now logs at debug level, so failures are diagnosable without changing user-visible behaviour. |
| 41 | **High** | Rigid pagination buttons across Applications and Processes limited UX and caused artificial paging delays. | Removed pagination across all views; implemented unified continuous smooth-scrolling `CTkScrollableFrame` containers with non-blocking progressive micro-batching. |
| 42 | **Critical** | Package listing and filtering relied solely on slow compound ADB queries (seconds per scan). | Implemented dedicated per-device SQLite storage (`device.db`) in WAL mode with fast composite indexing. Delivers sub-millisecond querying (0.20 ms) and background async atomic batch sync (0.59 ms). |
| 43 | Medium | Device storage organization had hardcoded model names in utility scripts. | Dynamic scanner (`get_known_devices()`) inspects actual storage directories dynamically with zero hardcoded device strings. |
| 44 | Medium | Battery voltage regex failed on multiline outputs and omitted charging/health states on Android 8. | Rewrote `_parse_battery` with multiline anchoring and full `BatteryManager` status (`Charging (AC/USB/Wireless)`, `Full`, `Good`, `Overheat`, etc.). |
| 45 | Medium | Scrcpy crashed on Android < 11 (API < 30) when default audio forwarding was attempted. | Automatically appends `--no-audio` when mirroring devices running Android 10 or earlier. |
| 46 | Low | `get_package_details_structured` leaked trailing punctuation (`}]"')>`) and non-class names into parsed activities and services. | Cleaned regex capture groups and filtered non-canonical class and UID strings. |
| 47 | **High** | Preset saving failed with `'ADBEngine' object has no attribute 'log'` because `ApplicationsView` invoked `self.engine.log()`. | Added canonical `ADBEngine.log(msg, level)` method that streams into `LOGGER` and the reactive `AUDIT_LOGGER`. |
| 48 | **High** | Windows file dialog (`Load App Selection Preset List`) showed a completely blank folder because space-separated extensions in `filetypes` (`"*.txt *.adac *.json *.csv"`) were treated by Win32 as a single invalid filter pattern. | Converted all multi-extension filetypes to tuples (e.g. `("*.txt", "*.adac", "*.json", "*.csv")`), allowing Windows Explorer to correctly list all compatible preset formats. |
| 49 | **Feature** | Local GGUF Gemma 4B integration (`gemma-4-E4B-it-Q4_K_M.gguf`) with managed background `llama-server.exe` engine and dedicated WAL `brain.db`. | Built `AIBrainEngine` and `BrainDatabase` providing instant local AI Copilot, interactive device queries, package safety analysis, and continuous learning. |
| 50 | **Feature** | Autonomous Self-Healing Sub-Agent (`AutoHealAgent`) with deterministic repair recipes for ADB disconnects, SQLite database lock contention, and Tkinter exceptions. | Added automated error interception with `report_callback_exception` that logs root causes to `brain.db` and recovers runtime state with zero UI freezing or crashes. |

**Checks run:** `pytest` (26 test suite: 100% PASS), built-in self-test suite (15/15 PASSED: 100%), `py_compile` (clean), `pyflakes` (clean), module import, a live auto-updater probe, SQLite WAL benchmarks (0.20 ms query, 0.59 ms batch sync), GUI construction with all nine views activated, HTML/JSON exporter round-trip, venv dependency import, and the full live suite on connected Samsung devices (111 PASS / 0 FAIL / 1 platform-limited).

---

## Audit pass — log forensics + runtime fixes (2026-11-20)

The shipped log set (4 files, ~16 MB) and a fresh static/dynamic review produced these findings and fixes:

| # | Severity | Finding | Fix |
|---|---|---|---|
| A1 | **High** | `Auto-Perms` sent `pm grant` for **every** declared permission. Signature/privileged permissions always fail: the logs contain **596 `SecurityException`** entries across `com.qti.*`, `com.vivo.*`, `com.android.*` and Google packages. | Only runtime permissions from `PERM_TO_APPOP_MAP` are attempted, and each package is granted in one pipelined shell call with a batched AppOps pass. |
| A2 | **High** | Every failed grant was audited as `FAILED`, which triggered `AutoHealAgent`, which asked Gemma for a diagnosis. A busy/loading 4B model then returned after the client timeout, producing **749 `Gemma query error: timed out`** warnings in one day and blocking a thread per failure. | The auto-heal agent now classifies permission/install refusals as expected platform policy, never calls the model for `ActionFailure`, rate-limits AI diagnosis to one call per 5 minutes, and the AI engine has a circuit breaker (3 timeouts → 120 s cooldown) plus a 90 s request timeout. |
| A3 | **Medium** | The live device watcher called the full `scan_devices()` every 3.5 s, which audits two commands per tick and re-runs `dumpsys` on every attached device — the main reason the log reaches ~20 MB/day. | The watcher now uses the unaudited `quick_poll_devices()` and only runs a full refresh when the serial set actually changes. |
| A4 | **Medium** | `organize_device_storage()` contained a hard-coded serial→folder map for five specific test phones, so it silently did nothing for any other device. | Device folders are discovered dynamically from the directories present under `backups/`, `exports/`, `screenshots/`, `video/`, `logs/` and `cache/device/`. |
| A5 | **Medium** | The Gemma model path was hard-coded to one user's `C:\Users\JMD\...` folder in two places. | A single `_discover_gguf_model()` resolves the first `.gguf` in `models/`, a sibling `MODEL`/`models` folder, or `~/Documents/MODEL`; a missing model is reported as `Model Missing` instead of failing at query time. |
| A6 | **Low** | `grant_permission` reported “Granted via AppOps” even when the AppOps call itself failed, and accepted unvalidated permission strings. | Permission names are validated against `android.permission.*`, AppOps success is checked, and failures are reported verbatim. |

### Second pass — engine/UI contract defects (2026-11-20)

A line-by-line review of every view and the remaining engine methods found contract mismatches that the first pass missed because they only fail at click time:

| # | Severity | Finding | Fix |
|---|---|---|---|
| B1 | **High** | The Live Console's Quick Terminal called `engine.run_adb(..., serial=...)` and then read `res.stdout`. `run_adb` takes `target_serial` and returns `(ok, out, err)`, so **every** terminal command raised `TypeError` inside a worker thread and silently produced nothing. | The call now uses the real signature and prints the command output (or an explicit “no output”/error line) back into the console. |
| B2 | **High** | `install_apks()` and `_install_bundle_archive()` never passed a device serial, so `adb install` refused with “more than one device” whenever two devices (e.g. USB + Wi-Fi) were attached. | `install_apks(..., serial="")` is threaded through single, split and bundle installs plus OBB pushes; both call sites (Install view, backup restore) pass the selected device. |
| B3 | **Medium** | `DeviceDatabase.sync_packages` read `b_info["desc"]`, a key that never exists, so every cached package description was stored empty. | Uses `b_info.get("description")` with a safe fallback. |
| B4 | **Medium** | `DeviceDatabase.get_all_packages` returned only package/type/enabled/path, so min SDK, target SDK, UID and install/update dates were always blank after a restart from cache. | The query now returns all persisted columns (`min_sdk`, `target_sdk`, `uid`, `first_install`, `last_update`). |
| B5 | **Medium** | `PresetPickerModal` created `tk.StringVar()` although `tk` is not imported in that module scope — the preset picker raised `NameError` the moment it was opened. | Uses `ctk.StringVar()`. |
| B6 | **Medium** | `PermissionsView.update_ui` mixed `and`/`or` without parentheses, so the empty-selection branch could override the populated-state badge. | Explicit parenthesised conditions. |
| B7 | **Medium** | The AI view still hard-coded one user's GGUF path in its banner/specs, and “Open Model Folder” called `os.path.dirname("")` when no model was found — a silent no-op. | Banner, model name and path come from the live engine path; the folder button explains where to place a `.gguf` instead of failing silently. |
| B8 | **Medium** | The auto-updater received `store.engine`, an attribute that does not exist (the engine lives at `store.adb_engine`), so post-update binary re-resolution never ran. | Correct attribute passed. |
| B9 | **Medium** | Copilot chat set the composer to “⏳ …” and then, when the brain engine was absent, cleared the flag from a worker thread without ever re-enabling the Send button — the chat stayed dead until restart. | The missing-engine case is reported on the UI thread before the composer locks; worker exceptions are caught and shown as a message. |
| B10 | **Low** | A non-numeric port in the Wi-Fi connect dialog raised `ValueError` inside the worker, leaving “Connecting…” forever. | The address is validated on the UI thread with a clear message. |
| B11 | **Low** | “Save Image” copied the capture with no error handling, silently did nothing when no capture existed, and crashed on same-file selection. | Missing capture is explained, same-file selection is a no-op message, copy errors are reported. |
| B12 | **Low** | `get_package_details_structured` reused the serial variable name `s` for each stripped `dumpsys` line. | Renamed to `line_s`. |
| B13 | **Low** | The header “Dev Mode” button only changed on completion; the Rescue card previously claimed success before the worker finished. | Both now report after the work completes. |
| B14 | **Low** | The live activity panel re-queued its idle poll every 50 ms (20 Hz of Tk wake-ups for nothing). | 150 ms poll; log draining is still batched. |

### Root & Developer Toolkit (new)

A new **Rescue → 0. Root & Developer Toolkit** card plus a **🐞 Dev Mode** header shortcut:

* **Enable Developer Options + USB Debugging** — one click sets `development_settings_enabled` and `adb_enabled`, reads both back, and explains the OEM fallback when a build blocks `settings put`.
* **Root & Bootloader Diagnostic** — reports su/Magisk presence, SELinux, verified-boot state, lock state, OEM-unlock allowance, SoC and the recommended rooting path for that exact device.
* **1-Click Root Assistant** — automates every step that can be automated: diagnostics, developer options, optional bootloader unlock (`fastboot flashing unlock` with `oem unlock` fallback, explicit destructive confirmation), Magisk manager install from the latest GitHub release, and a precise report of the remaining device-specific step.
* **Install Latest Magisk** — resolves the newest `topjohnwu/Magisk` release asset and installs it on the selected device.

There is **no universal one-click root**: the last step always flashes a boot image patched for one exact firmware build. The assistant does everything up to that point and states plainly what remains, rather than pretending an unsupported device was rooted.

**Checks run for this pass:** `py_compile` clean; built-in self-test suite **15/15 PASSED**; a stubbed `ADBEngine` proving `install_apks(serial=...)` routes `target_serial` into the real `adb install` call and that `run_adb` returns the `(ok, out, err)` tuple the console now unpacks; AST checks confirming the touched classes have a single definition of each method and that `_open_model_folder` is attached to `AIBrainView`; and the new engine methods with no device attached (all return clear guidance instead of raising). The on-device root/unlock flows were **not** executed — they require a physical device, a bootloader reboot and data loss — so they remain unverified on hardware. No UI was clicked through in this pass; the changed views were verified by compile, self-test and stubbed engine calls only.

---

## v2.0 — Safety, maintenance & delivery (2026-11-20)

This pass implements the full follow-up list from the audit retrospective. Everything below is in the shipped single file unless noted.

| Area | What shipped |
|---|---|
| **Undo safety net** | `MutationJournal` records every reversible mutation (disable, uninstall) with the exact inverse shell command and the serial it was applied to. `Settings → Safety Net` offers **↩ Undo Last Action** and **📜 Undo History** (last 25 entries, per-row undo). Journal is capped at 300 entries, crash-safe (atomic replace) and exported with diagnostics. |
| **Secrets at rest** | PIN verifiers are now **PBKDF2-HMAC-SHA256** (260k iterations, random salt) and the verifier string is sealed with **Windows DPAPI** (`CryptProtectData`), so another Windows account cannot reuse it. Legacy unsalted SHA-256 verifiers still work and are upgraded on the next successful unlock. Non-Windows falls back to a base64 form, documented rather than pretended. |
| **Cache hygiene** | `cache_report()` groups the cache by subfolder; **Prune Cache** deletes oldest-first until the configurable budget (`cache_budget_mb`, default 250 MB) is met, then removes empty folders. Backups, exports, screenshots, video and logs are never touched. |
| **Diagnostics bundle** | One click writes a zip with the last four log files, a **PIN-redacted** config, versions/paths, device list, undo journal and OEM profile — the thing to attach to a bug report. |
| **OEM profiles** | `presets/oem_profiles.json` is generated with Samsung, Xiaomi/Redmi/POCO, OPPO/OnePlus/realme, vivo/iQOO, Motorola and generic entries (debloat cautions, developer-options hints, rooting notes, critical packages). It is data, not code: add a device by editing JSON. The Root Assistant appends the matched profile's notes. |
| **Wireless reliability** | Pairing tab gains **mDNS discovery** (`adb mdns services`) that fills the pair/connect address; successful connects are remembered in `wireless_history`; the device watcher retries known wireless endpoints (throttled to 45 s) when they drop off after sleep or a network change. |
| **AI hardening** | Device-supplied strings (model, serial, Android label, user text) are sanitised and wrapped in explicit `<device_data>` / `<user_request>` delimiters, with a system instruction to treat them as data only. A deterministic **offline copilot** answers battery/package/direct-command questions when no GGUF is loaded instead of leaving the panel inert. |
| **Interface scaling & shortcuts** | Auto-follows the Windows DPI (`GetDpiForSystem`) with a manual `auto / 100 / 125 / 150` override in Settings; minimum window reduced to 1100×680. Shortcuts: `Ctrl+1…0` switch pages, `F5` rescan, `Ctrl+F` focus the application search, `Ctrl+Q` quit. |
| **Tests & CI** | `tests/test_contracts.py` (18 pytest cases) guards the exact class of bug that broke click-time features: `run_adb` signature/tuple contract, serial-aware installs, journal record/undo/cap, PIN salting + legacy upgrade, prompt sanitisation, cache pruning, diagnostics redaction, OEM profile loading. `.github/workflows/ci.yml` runs pytest plus the in-app 15-case suite on Windows. |
| **Packaging** | `appcontrol.spec` (PyInstaller, one-directory, no console) and `build_release.bat` produce `dist/ADB_AppControl/ADB_AppControl.exe`; `.gitignore` keeps runtime data and build output out of the repo. `--version` prints `ADB AppControl 2.0.0`. |

**Deliberately deferred (with reasons, not forgotten):**

* **Module split into `engine/`, `db/`, `ui/`** — a 13k-line rewrite would destabilise every verified flow at once. The contract tests and CI added here make an incremental extraction safe to do next, one module at a time.
* **Explicit multi-device session objects** — installs are now serial-scoped, but backup/pull/screenshot/logcat still resolve the “current device”. Correct concurrency needs a session object threaded through the engine and a per-device queue; that is an architecture change, not a patch.
* **Code signing and app self-update** — both require a certificate and a release host; the spec and build script produce the artifact those steps consume.

## Live hardware verification — Samsung SM-G935F (Android 8.0.0, 2026-11-20)

Every engine feature that can run without root, fastboot mode or data loss was executed against a real attached device (`ce01171132d09d4005`). **33/33 live checks passed** after the fixes below; the four problems found were all silent-failure bugs that only real hardware exposes.

| # | What the device exposed | Fix |
|---|---|---|
| H1 | `--audit` aborted on `get_device_specs`: `'charmap' codec can't encode character '\U0001f50b'`. Python's Windows stdout defaults to cp1252 and the battery string contains 🔋. | `sys.stdout`/`sys.stderr` are reconfigured to UTF-8 with `errors="replace"` at import, so the audit and any CLI output survive status glyphs. |
| H2 | The copilot's **battery** intent called `adb_engine.get_battery_info()`, a method that does not exist — the action always died with `AttributeError`. | Uses `get_battery_details()` (both the intent and the offline copilot). |
| H3 | Live logcat delivered **27,140 lines in 4 s** (the whole device backlog) into the UI callback, burning CPU before a single new line arrived. | The stream now starts with `logcat -T 200` (tail 200, then follow) and restarts once without `-T` on older builds that reject it. Measured **441 lines / 3 s** afterwards (≈60× less churn). |
| H4 | `get_clipboard()` returned the literal text **"Unknown package"**: the Android 8 binder call fails and its exception parcel was decoded as clipboard content. `set_clipboard()` also claimed success on that build although neither path exists. | Failed parcels are rejected by their status word and error text; unsupported clipboard writes now say so plainly instead of claiming success. |
| H5 | The Permissions view's **"Revoked Only"** filter could never populate: Android 8's global `dumpsys package` omits revoked permissions entirely (verified: revoked package section shrinks to 1.5 KB with no mention of the permission), and even `dumpsys package -a` omits the requested-permissions block. | The scanner keeps the fast global dump for granted permissions, then reads declarations for third-party packages in one batched per-package shell pass. On the test device this correctly reports **4 revoked apps** (`acbridge`, WhatsApp, truecaller, LocalSend) in 2.6 s, cached 90 s. `not_requested` is now the real installed-minus-known set. |
| H6 | The app-detail inspector showed only granted permissions (revoked ones vanished), so "Declared Permissions" under-reported. | Manifest declarations are merged back in and marked not-granted — verified: `READ_EXTERNAL_STORAGE` shows granted=true/false as the state changes. |
| H7 | `grant_permission()` answered **"Granted via AppOps"** for `RECORD_AUDIO` on an app that never declared it — setting an AppOp is not a permission grant and the OS still denies it. | The package's declarations are checked first; undeclared permissions are refused with an explanation and no `pm grant` is attempted. Real refusals now read "pm grant refused (…); AppOps mode set as best-effort fallback". |
| H8 | `pm hide` falls back to `disable-user` (no root), but that mutation was invisible to the undo journal; and restoring a package by hand left a stale "pending" entry. | The fallback is journaled, and `enable_app` / `unhide_app` / `restore_system_app` now close matching pending entries (verified: pending 1 → 0 after restore). |
| H9 | Root diagnostics reported `bootloader: unknown` on this Samsung: it exposes neither `ro.boot.verifiedbootstate` nor `ro.boot.flash.locked` to a non-root shell. | Falls back to the Knox warranty bit (`ro.boot.warranty_bit`): intact → locked, tripped → unlocked, with the inference stated. The Root Assistant also says whether `OEM unlocking` is currently allowed (`sys.oem_unlock_allowed=1` here). |

**Verified working on the device (not just compiled):** device scan + quick poll, full telemetry, specs, battery, RAM, storage, display scaling, WLAN IP, 342-process listing, 349-package inventory (253 installed / 96 uninstalled — matches raw `pm list` exactly), package details, permission scanning, root status, OEM profile match, screenshots (683 KB), logcat dump, remote mkdir/push/rename/pull/chmod/delete, APK backup + backup-manager scan, screenshot/bundle export, cache pruning (303 MB → 200 MB), developer-options shortcut (`settings` confirmed 1/1), device-data export, storage organization, and a **real APK reinstall** of a user app (`Success`).

**Hardware-verified safety net:** disabling a preinstalled app put it in `disabled-user`, the journal recorded it, **Undo** restored it to `enabled`, and a fresh engine instance still read the journal with 0 pending entries.

**Not exercised (needs conditions this device cannot provide):** fastboot/MTP write actions (device never entered fastboot), bootloader unlock/Magisk/root (destructive, requires reboot and data loss), Wi-Fi switching (would drop the ADB session), screen recording and scrcpy launch (open windows / capture the user's screen), `send_key`/`send_tap`/`send_text` (would drive the phone), `auto_grant_all_permissions` and `restore_all_disabled` (would change permissions or reinstall 96 packages on the user's phone). These remain code-reviewed and contract-tested only.

## Static audit pass — UI state, threading & multi-device (2026-11-20)

A block-by-block review of the view layer (applications, debloat, process, permissions, rescue, screen, install, terminal, settings, AI brain, live console) found ten defects. None were crash-visible; every one produced a wrong belief about the device or a latent cross-thread Tk call.

| # | Defect | Fix |
|---|---|---|
| C1 | `winfo_exists()` was called from three background workers (`load_display_info`, `capture_screen`, `refresh_file_explorer`), a Tk call off the UI thread. | Workers now only schedule `after(0, …)`; the liveness check happens inside the UI callback. |
| C2 | Single-row **Disable / Enable / Restore / Uninstall** updated the cached package state unconditionally, so a *refused* action still rendered the app as disabled or uninstalled until the next full scan. | `result_indicates_success()` classifies the engine reply and the row state only changes for accepted actions. |
| C3 | The same optimistic-state bug existed in **batch** Enable/Disable/Hide/Restore, **batch uninstall** and the **Debloat wizard**, which marked every selected package regardless of per-package outcome. | All three now apply changes only to the subset whose results indicate success; the per-package report still lists every failure verbatim. |
| C4 | Batch actions called `func(pkg)` and let the engine resolve the device inside the worker, so switching devices mid-batch could send the remaining packages to the *new* device. | The serial is captured once at click time and passed to every call (with a `TypeError` fallback for methods without the keyword). |
| C5 | ConsoleView's live-logcat callback read `self.lc_filter_var.get()` from the reader thread — a Tk variable touched off the UI thread. | A `trace_add` mirror keeps a plain-string copy (`_lc_filter_kw`) that the reader thread uses. |
| C6 | Remote `pull` / `push` / `mkdir` / `rename` / `delete` in the file explorer omitted the target serial, so with two devices attached they could act on the wrong one. | Every remote file call now passes the serial selected at click time. |
| C7 | "Inspect local APK" parsed the archive on the UI thread; large XAPK/APKS bundles froze the window for seconds. | Parsing moved to a worker with an `after` handoff. |
| C8 | Closing the app while logcat was streaming left the reader thread feeding a destroyed view. | `_on_close` stops the logcat stream before tearing down widgets. |
| C9 | The preset picker listed `presets/oem_profiles.json` as a selectable package list (0 packages) after OEM profiles were added. | Configuration files are skipped when gathering presets. |
| C10 | Model Info hard-coded weight size and engine build (`4.64 GB`, `b12474`) and always claimed "Online"; the port probe attached to *any* service answering `/health`; Auto-Heal Audit silently did nothing when the brain was offline. | Specs are computed from the real model file and engine path, status reflects `is_ready`, only a JSON `{status: …}` health reply is adopted as llama-server, and the audit explains that the brain is not running. |

Checks after this pass: `py_compile` clean, `pytest tests` **31 passed**, built-in `--test` **15/15**, headless view build **5/5**. No new hardware-dependent behaviour was introduced, so the SM-G935F verification table above remains valid.

### Live proof of the state-accuracy fix (SM-G935F, 2026-11-20)

The real `ApplicationsView` was built in a withdrawn Tk window (real `mainloop`) and driven through the same methods a button click runs. **19/19 checks passed**, exit code 0, ~37 s, phone left clean afterwards (0 disabled packages, journal pending 0, Clock enabled).

| Step | Evidence |
|---|---|
| Row before action | rendered row pill = `ENABLED`; device reports `enabled` |
| Disable `com.sec.android.app.clockpackage` through `_single_action` | store `enabled=False`; row pill = `DISABLED`; `pm list packages -d` lists it; journal pending 0 → 1 |
| `undo_last_mutation()` | device re-enabled; row pill back to `ENABLED`; journal pending back to 0 |
| Disable attempt against an unreachable ADB target | real failure `adb.exe: device '…' not found`; store stayed `enabled=True`; row stayed `ENABLED`; device untouched; nothing journaled |
| Device refusal `Failure [not installed for 0]` | reported as failure; `_single_uninstall` left the row `UNINSTALLED`; nothing journaled |

The run found two real defects the static pass had missed:

| # | Defect | Fix |
|---|---|---|
| C11 | `result_indicates_success()` did not recognise ADB transport failures — the live reply `adb.exe: device '…' not found` contains none of the old keywords (`failure`, `error`, …), so a disable that never reached the phone still flipped the row to DISABLED. | Failure keywords extended with `not found`, `no devices`, `cannot`, `unable`, `invalid`, `not installed`; three new regression cases cover the exact live strings. |
| C12 | `uninstall_app()`'s fallback forced `pm uninstall -k --user 0`, so the UI's "Keep app data" choice was ignored (and an unchecking of "current user only" still removed the package for user 0). Proven live: uninstalling the Clock app with `keep_data=False` used `-k`. | The fallback reuses the caller's `k_flag`; tests assert `-k` appears only when `keep_data=True`. |

Caveat on the harness: Tk's `after()` from worker threads is unreliable under a headless driver (it intermittently raised `main thread is not in main loop`, which the real mainloop does not do), so the script routes only the view's `after` through a queue drained on the UI thread. The production state logic under test is untouched.

During probing, `pm disable-user` was found to answer "new state: disabled" even for a package that does not exist on Android 8, so a refusal has to come from `pm uninstall` (or an unreachable ADB target) — those are the two failure cases above.

### Explicit action results replace text matching (2026-11-20)

The UI no longer guesses whether a package action worked by reading `pm` prose. Mutating engine methods return an `ActionResult`: a `str` subclass that carries the message **and** an explicit `ok` flag, so logging, dialogs, the copilot and the batch summaries keep working unchanged while call sites read `.ok`.

| Producer | Where `ok` comes from |
|---|---|
| `disable_app` / `enable_app` / `restore_system_app` / `hide_app` / `uninstall_app` | A device-state probe (`pm list packages -e` / `-d`) after the action. Android answers "new state: disabled" even for a package that does not exist, and exits 0 while printing `Failure [...]`, so neither the exit status nor the message is trusted. `uninstall_app` probes before and after, so "already uninstalled" is a refusal, not a success. |
| `grant_permission` / `revoke_permission` | The permission's `granted=true/false` line in `dumpsys package`. AppOps fallbacks report `ok=False` because the permission is not actually granted. |
| `force_stop_app` / `clear_data` | The shell exit status (these do not model row state; `am force-stop` prints nothing on success). |

Call sites reading the flag: `_single_action`, `_single_uninstall`, `_restore_system_app`, `_batch_apply_action`, `_batch_uninstall_dialog`, `_apply_debloat`, the Permissions bulk grant/revoke, `restore_all_disabled` and the copilot's uninstall intent. The classifier (`result_indicates_success`), its regexes and its package-token neutralisation are gone, along with the residual limits they carried: mixed `||` fallback output, unfamiliar error wording and success text containing failure words no longer affect the decision at all.

Cost: one extra `adb shell` round trip per action (two for uninstall) for the state probe, measured at ~1.3 s because it reads both the enabled and the disabled package lists. Batch debloat therefore gained ~1.3 s per selected package; the APK backups it already performs dominate the run time.

Empty-output failures are no longer dressed up as success: `_reply()` prefers the device's own reply and otherwise states the real outcome, and it now backs `clear_data`, `clear_cache`, `compile_app`, USB-mode switching, boot-slot changes, partition erase/factory reset, fastboot reboot, screen power, display size/density, dark mode, animation scales, stay-awake, logcat clearing, and reboot/power-off. `hide_app` additionally reports "already disabled" instead of "Hidden." when the package was disabled before the call, and takes its flag from the resulting state rather than the exit status.

Also in this pass: `_call_with_serial` replaced two `try/except TypeError` wrappers that could execute an action twice; serials are pinned for batch auto-permissions and bulk grant/revoke; `disable_app` / `enable_app` / `force_stop_app` no longer invent `"Disabled."`-style success when the shell failed silently; the logcat filter mirror dropped a pointless `try/except`.

## Known limitations

* Windows-first: macOS/Linux rely on untested code paths.
* `pm hide` requires root on Android 10+; without it the app falls back to `disable-user`.
* `adb install` of a pulled OEM system APK is refused by the vendor build type (`INSTALL_FAILED_REJECTED_BY_BUILDTYPE`) — expected, not a bug.
* Paths containing command-substitution syntax are quoted safely (nothing executes) but some Android storage layers store a truncated name; ordinary names with spaces, quotes and semicolons round-trip exactly.
* MTP transfers are delegated to the OS file manager; there is no in-app MTP browser.
* Python library upgrades take effect on the **next launch** — Windows cannot replace a loaded `.pyd` — and the updater only manages `customtkinter`, `Pillow` and `pyaxmlparser`.
* The app's own source is not self-updating (this workspace has no git remote); updates cover the packages and tool repos it consumes.
* Page size and A/B slot are reported read-only; the app never rewrites boot slots or partitions outside the explicit fastboot actions.
* No partition-level backup/restore (boot images, EFS, full NAND dumps).
* The single-file monolith (`appcontrol.pyw`) embeds its own automated test suite and live hardware auditor directly inside itself (`--test` / `--audit`).
* PIN protection is a salted PBKDF2 verifier sealed with Windows DPAPI; it gates the UI, it does not encrypt device data or backups.
* The undo journal covers reversible package operations (disable/uninstall). `pm clear`, cache wipes and partition writes are inherently not undoable and are not recorded as if they were.
