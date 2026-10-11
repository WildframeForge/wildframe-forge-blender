# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared discovery of running Wildframe Forge apps (Blender and Unreal) on this computer.

Each running app writes ``<state>/Instances/<app>-<pid>.json``:

    {"schema": "WILDFRAME_INSTANCE_V1", "app": "blender" | "unreal", "pid": 1234,
     "endpoint": "http://127.0.0.1:19950/wildframe/v1", "tokenFile": "...",
     "version": "1.0.0", "document": "C:/scenes/ship.blend", "heartbeat": "2026-10-07T12:00:00Z"}

``<state>`` is %LOCALAPPDATA%/Wildframe Forge on Windows and ~/.wildframe elsewhere. Records whose process is gone
or whose heartbeat is older than ``STALE_SECONDS`` are ignored (and cleaned up when possible).
"""

import datetime
import json
import os
import sys

SCHEMA = "WILDFRAME_INSTANCE_V1"
STALE_SECONDS = 120


def state_dir():
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "WildframeForge")
    return os.path.join(os.path.expanduser("~"), ".wildframe")


def instances_dir():
    path = os.path.join(state_dir(), "Instances")
    os.makedirs(path, exist_ok=True)
    return path


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_seconds(iso):
    try:
        then = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - then).total_seconds()
    except Exception:  # noqa: BLE001
        return 1e9


def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def record_path(app, pid=None):
    return os.path.join(instances_dir(), "%s-%d.json" % (app, pid or os.getpid()))


def atomic_write_json(path, data, retries=6, delay=0.05):
    """Write JSON to ``path`` through a temp file unique to this process and call, then os.replace.

    Other processes (the hub, another Blender, Unreal) write the same files, so a fixed ``.tmp`` name could be
    clobbered or replaced mid-write. On Windows os.replace fails with PermissionError while a reader has the
    target open; that is retried a few times with a short back-off."""
    import secrets
    import time
    tmp = "%s.%d.%s.tmp" % (path, os.getpid(), secrets.token_hex(4))
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        for attempt in range(max(1, retries)):
            try:
                os.replace(tmp, path)
                return path
            except PermissionError:
                if attempt == max(1, retries) - 1:
                    raise
                time.sleep(delay * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


def write_record(record):
    record = dict(record)
    record.setdefault("schema", SCHEMA)
    record.setdefault("pid", os.getpid())
    record["heartbeat"] = now_iso()
    path = record_path(record["app"], record["pid"])
    return atomic_write_json(path, record)


def remove_record(app, pid=None):
    try:
        os.remove(record_path(app, pid))
    except OSError:
        pass


# A normal quit must remove the record, or the hub would take it for a crash and may reopen Blender.
# Blender normally unregisters the add-on on quit; atexit covers the cases where it does not. A crash
# skips both, which is what the hub relies on.
_atexit_apps = set()


def remove_record_at_exit(app):
    import atexit
    if app in _atexit_apps:
        return
    _atexit_apps.add(app)
    pid = os.getpid()
    atexit.register(lambda: remove_record(app, pid))


def read_token(record):
    path = record.get("tokenFile")
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def list_instances(app=None):
    """Live records, newest heartbeat first. Dead records are deleted."""
    out = []
    folder = instances_dir()
    for name in os.listdir(folder):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                rec = json.load(handle)
        except Exception:  # noqa: BLE001
            continue
        if rec.get("schema") != SCHEMA or (app and rec.get("app") != app):
            continue
        alive = pid_alive(rec.get("pid"))
        if not alive:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        if _age_seconds(rec.get("heartbeat", "")) > STALE_SECONDS:
            continue
        out.append(rec)
    out.sort(key=lambda r: r.get("heartbeat", ""), reverse=True)
    return out
