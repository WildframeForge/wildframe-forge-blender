# SPDX-License-Identifier: GPL-3.0-or-later
"""Local HTTP server that lets AI tools and the Wildframe Forge Unreal plugin drive Blender.

Safety model
- Listens on 127.0.0.1 only; every route except /health needs the per-session token
  (``X-Wildframe-Token: <token>`` or ``Authorization: Bearer <token>``).
- Requests that carry a browser ``Origin`` header are refused, so web pages cannot reach it.
- Request bodies are capped (MAX_BODY_BYTES).
- HTTP threads never touch ``bpy``. They queue a job; a ``bpy.app.timers`` pump runs jobs on Blender's
  main thread, one per tick, and every job is wrapped so a failing command cannot stop the pump.

Routes (all JSON):
  GET  /wildframe/v1/health                      no auth, {"status": "ready", "queue": {...}}
  GET  /wildframe/v1/info                        app, version, file, port, queue
  GET  /wildframe/v1/capabilities                every command with its schema
  POST /wildframe/v1/commands  {command, params, waitSec}   -> {job, queue} (result included if it finished in time)
  GET  /wildframe/v1/jobs/status?jobId=...       -> {job, queue}
  GET  /wildframe/v1/jobs/by-request?requestId=  -> {job, queue} of the job submitted with that X-Wildframe-Request-Id
  POST /wildframe/v1/jobs/cancel {jobId}         cancels a job that has not started yet

Several AI clients (separate connector processes) can share one Blender session:
- ``X-Wildframe-Client: <name>#<pid>`` identifies the caller (``"unknown"`` when absent); it is stored on the job
  together with ``X-Wildframe-Request-Id``. A submit that repeats a known request id returns the existing job with
  ``"duplicateOf": true`` instead of running the command twice (safe retries).
- Jobs run one at a time in submit order. ``queue`` tells a caller where its job stands:
  ``{"position": 0 running | k jobs ahead | -1 finished, "queuedCount", "activeJobId", "activeCommand",
  "activeClient", "backgroundCount"}`` (``position`` only where a job is concerned; a QUEUED job with nothing
  ahead also reports 0 for the moment before the pump starts it - read ``state`` to tell).
- Every state change of a job happens under one lock, so a cancelled job can never start.
- Each undo step the bridge pushes remembers the client that caused it; EDITOR.UNDO refuses to undo another
  client's step unless ``force`` is true (``UNDO_OTHER_CLIENT``).
"""

import collections
import json
import os
import secrets
import socket
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import bpy

from . import instances, registry

API = "/wildframe/v1"
MAX_BODY_BYTES = 32 * 1024 * 1024
MAX_JOBS_KEPT = 300
MAX_UNDO_JOURNAL = 200
DEFAULT_PORT = 19950
VERSION = "1.0.0"
UNKNOWN_CLIENT = "unknown"
ACTIVE_STATES = ("QUEUED", "RUNNING", "WAITING")

_state = {
    "server": None,
    "thread": None,
    "port": 0,
    "token": "",
    "token_file": "",
    "jobs": collections.OrderedDict(),
    "queue": collections.deque(),
    "by_request": {},       # X-Wildframe-Request-Id -> jobId
    "active": None,         # jobId running on the main thread right now
    "undo": [],             # undo steps the bridge pushed, oldest first: {"jobId", "client", "command"}
    "redo": [],             # steps undone through EDITOR.UNDO, most recent last
    # RLock: _finish() takes it and is also called while it is held (stop(), cancel)
    "lock": threading.RLock(),
    "pump": False,
}


# ------------------------------------------------------------------ jobs

def _clean_header(value, limit=200):
    value = "".join(ch for ch in str(value or "") if ch.isprintable()).strip()
    return value[:limit]


def _evict_finished_locked():
    """Drop the oldest finished jobs beyond MAX_JOBS_KEPT. Queued/running/waiting jobs are never evicted."""
    excess = len(_state["jobs"]) - MAX_JOBS_KEPT
    if excess <= 0:
        return
    for job_id in [jid for jid, j in _state["jobs"].items() if j["state"] not in ACTIVE_STATES][:excess]:
        job = _state["jobs"].pop(job_id)
        rid = job.get("requestId")
        if rid and _state["by_request"].get(rid) == job_id:
            del _state["by_request"][rid]


def _new_job(command, params, client=None, request_id=None):
    """Create and queue a job. Returns (job, duplicate): a known request id returns its existing job."""
    client = _clean_header(client) or UNKNOWN_CLIENT
    request_id = _clean_header(request_id) or None
    with _state["lock"]:
        if request_id:
            existing = _state["jobs"].get(_state["by_request"].get(request_id, ""))
            if existing is not None:
                return existing, True
        job = {
            "jobId": str(uuid.uuid4()),
            "command": str(command or "").upper(),
            "params": params or {},
            "state": "QUEUED",
            "client": client,
            "requestId": request_id,
            "created": time.time(),
            "started": None,
            "finished": None,
            "result": None,
            "event": threading.Event(),
        }
        _state["jobs"][job["jobId"]] = job
        if request_id:
            _state["by_request"][request_id] = job["jobId"]
        _state["queue"].append(job["jobId"])
        _evict_finished_locked()
    return job, False


def find_by_request(request_id):
    with _state["lock"]:
        return _state["jobs"].get(_state["by_request"].get(_clean_header(request_id), ""))


def queue_info(job=None):
    """Queue snapshot; with a job also its position (0 running, k jobs ahead, -1 finished)."""
    with _state["lock"]:
        queued = [jid for jid in _state["queue"]
                  if (_state["jobs"].get(jid) or {}).get("state") == "QUEUED"]
        active = _state["jobs"].get(_state["active"] or "")
        out = {
            "queuedCount": len(queued),
            "activeJobId": active["jobId"] if active else None,
            "activeCommand": active["command"] if active else None,
            "activeClient": active["client"] if active else None,
            "backgroundCount": sum(1 for j in _state["jobs"].values() if j["state"] == "WAITING"),
        }
        if job is not None:
            if job["state"] in ("RUNNING", "WAITING"):
                position = 0
            elif job["state"] == "QUEUED":
                # jobs ahead = queued jobs before it, plus the one running now
                ahead = queued.index(job["jobId"]) if job["jobId"] in queued else 0
                position = ahead + (1 if active else 0)
            else:
                position = -1
            out = dict({"position": position}, **out)
    return out


def _public_job(job):
    out = {k: job[k] for k in ("jobId", "command", "state")}
    out["client"] = job.get("client") or UNKNOWN_CLIENT
    if job.get("requestId"):
        out["requestId"] = job["requestId"]
    out["durationSec"] = round((job["finished"] or time.time()) - (job["started"] or job["created"]), 3)
    if job["result"] is not None:
        out["result"] = job["result"]
    return out


def _job_payload(job, duplicate=False):
    data = {"job": _public_job(job), "queue": queue_info(job)}
    if duplicate:
        data["job"]["duplicateOf"] = True
        data["duplicateOf"] = True
    return data


def _finish(job, result, state=None):
    """Record a job's result once. A job that is already finished (cancelled, stopped) keeps its outcome."""
    with _state["lock"]:
        if job["finished"] is not None:
            return False
        job["result"] = result
        job["state"] = state or ("COMPLETED" if result.get("ok") else "FAILED")
        job["finished"] = time.time()
        if _state["active"] == job["jobId"]:
            _state["active"] = None
    job["event"].set()
    return True


def cancel(job_id):
    """Cancel a queued job atomically with the pump. Returns (job or None, error code or None)."""
    with _state["lock"]:
        job = _state["jobs"].get(str(job_id or ""))
        if job is None:
            return None, "JOB_NOT_FOUND"
        if job["state"] != "QUEUED":
            return job, "JOB_NOT_CANCELLABLE"
        _finish(job, registry.envelope(False, "CANCELLED", "Cancelled before it started."), state="CANCELLED")
        try:
            _state["queue"].remove(job["jobId"])
        except ValueError:
            pass
    return job, None


def _run_background(job, fn, earlier_warnings=None):
    try:
        data = fn()
        data = data if isinstance(data, dict) else {"value": data}
        warnings = list(earlier_warnings or []) + list(data.pop("_warnings", []) or [])
        _finish(job, registry.envelope(True, "OK_WITH_WARNINGS" if warnings else "OK", "", data, warnings))
    except registry.CommandError as error:
        _finish(job, registry.envelope(False, error.code, error.message, error.data))
    except Exception as error:  # noqa: BLE001
        _finish(job, registry.envelope(False, "PYCMD_EXCEPTION", "%s: %s" % (type(error).__name__, error),
                                       {"error": {"traceback": traceback.format_exc()[-registry.MAX_TRACEBACK_CHARS:]}}))


def current_job():
    """The bridge job running on the main thread right now (None for UI, mailbox and AI-script calls)."""
    with _state["lock"]:
        return _state["jobs"].get(_state["active"] or "")


def current_client():
    job = current_job()
    return job["client"] if job else None


def _take_next_locked():
    while _state["queue"]:
        candidate = _state["jobs"].get(_state["queue"].popleft())
        if candidate and candidate["state"] == "QUEUED":
            candidate["state"] = "RUNNING"
            candidate["started"] = time.time()
            _state["active"] = candidate["jobId"]
            return candidate
    return None


def _record_undo_step(job):
    with _state["lock"]:
        _state["undo"].append({"jobId": job["jobId"], "client": job["client"], "command": job["command"]})
        del _state["undo"][:-MAX_UNDO_JOURNAL]
        _state["redo"] = []


def client_name(client):
    """``"<name>#<pid>"`` -> ``"<name>"``: the pid changes when an AI app restarts its connector, but it is
    still the same AI app (and user). Ids without '#' come back unchanged."""
    client = str(client or "")
    head, sep, _pid = client.rpartition("#")
    return head if sep and head else client


def same_client(a, b):
    """Same AI app = same name part; the unknown client never matches."""
    name = client_name(a)
    return bool(name) and name != UNKNOWN_CLIENT and name == client_name(b)


def check_undo(steps, force=False, client=None):
    """Raise UNDO_OTHER_CLIENT if undoing ``steps`` would take back another client's bridge step.

    ``client`` defaults to the client of the running bridge job; calls that do not come from a bridge job
    (the Blender UI, AI-script jobs, the mailbox) are the user and are never refused. Returns the journal
    entries the undo would take back, newest first. Best effort: Blender's own undo stack also holds the
    user's manual edits, which the journal cannot see."""
    client = current_client() if client is None else client
    steps = max(0, int(steps or 0))
    with _state["lock"]:
        taking = list(reversed(_state["undo"][-steps:])) if steps else []
    if client and not force:
        others = [e for e in taking if not same_client(e["client"], client)]  # same AI app, any pid
        if others:
            raise registry.CommandError(
                "UNDO_OTHER_CLIENT",
                "Undo would take back %d step(s) made by another AI client (%s). Pass force=true to undo anyway, "
                "or ask that client to undo its own work."
                % (len(others), ", ".join(sorted({e["client"] for e in others}))),
                {"steps": taking, "yourClient": client})
    return taking


def note_undone(count):
    """EDITOR.UNDO reports how many steps it really undid: move them to the redo journal."""
    with _state["lock"]:
        for _ in range(max(0, int(count))):
            if not _state["undo"]:
                break
            _state["redo"].append(_state["undo"].pop())


def note_redone(count):
    with _state["lock"]:
        for _ in range(max(0, int(count))):
            if not _state["redo"]:
                break
            _state["undo"].append(_state["redo"].pop())


def _clear_undo_journal(*_args):
    with _state["lock"]:
        _state["undo"] = []
        _state["redo"] = []


def _pump():
    """Runs on Blender's main thread via bpy.app.timers. Returns the next interval."""
    if not _state["pump"]:
        return None
    with _state["lock"]:
        job = _take_next_locked()  # QUEUED -> RUNNING under the same lock cancel() uses
    if job is None:
        return 0.05
    try:
        result = registry.run(job["command"], job["params"])
    except Exception as error:  # noqa: BLE001 - belt and braces; registry.run already catches
        result = registry.envelope(False, "PYCMD_EXCEPTION", str(error))
    background = None
    if result.get("ok") and isinstance(result.get("data"), dict):
        background = result["data"].pop("_background", None)
    if callable(background):
        with _state["lock"]:
            if job["finished"] is None:
                job["state"] = "WAITING"
            if _state["active"] == job["jobId"]:
                _state["active"] = None
        threading.Thread(target=_run_background, args=(job, background, result.get("warnings")), daemon=True).start()
    else:
        mutated = result.get("ok") and registry.all_commands().get(job["command"], {}).get("mutating")
        if mutated:
            # push (and journal) before releasing waiters, so a client that undoes right after sees its step
            try:
                bpy.ops.ed.undo_push(message="Wildframe Forge: %s (%s)" % (job["command"], job["client"]))
                _record_undo_step(job)
            except Exception:  # noqa: BLE001 - undo push needs a window context; ignore when headless
                pass
        _finish(job, result)
    with _state["lock"]:
        if _state["active"] == job["jobId"]:
            _state["active"] = None
        more = bool(_state["queue"])
    return 0.0 if more else 0.05


def submit(command, params, wait_sec=0.0, client=None, request_id=None):
    """Queue a command (or find the job of a repeated request id) and optionally wait. Returns (job, duplicate)."""
    job, duplicate = _new_job(command, params, client, request_id)
    if wait_sec > 0 and job["state"] in ACTIVE_STATES:
        job["event"].wait(timeout=min(float(wait_sec), 55.0))
    return job, duplicate


# ------------------------------------------------------------------ http

class _Handler(BaseHTTPRequestHandler):
    server_version = "WildframeForgeBlender/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silence the default stderr log
        return

    def _send(self, code, payload):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, code, err, message):
        self._send(code, {"ok": False, "error": {"code": err, "message": message}})

    def _authorized(self):
        supplied = self.headers.get("X-Wildframe-Token", "")
        if not supplied:
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()
        return bool(supplied) and bool(_state["token"]) and secrets.compare_digest(supplied, _state["token"])

    def _client(self):
        return _clean_header(self.headers.get("X-Wildframe-Client")) or UNKNOWN_CLIENT

    def _request_id(self):
        return _clean_header(self.headers.get("X-Wildframe-Request-Id")) or None

    def _guard(self):
        origin = self.headers.get("Origin")
        if origin and origin.lower() != "null":
            self._fail(403, "BROWSER_ORIGIN_REJECTED", "Requests from web pages are not accepted.")
            return False
        if not self._authorized():
            self._fail(401, "UNAUTHORIZED", "Send the session token as X-Wildframe-Token or Authorization: Bearer.")
            return False
        return True

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("Request body too large (%d bytes, limit %d)." % (length, MAX_BODY_BYTES))
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("Body must be a JSON object.")
        return data

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        route = url.path.rstrip("/")
        if route == API + "/health":
            return self._send(200, {"ok": True, "data": {"status": "ready", "app": "blender", "version": VERSION,
                                                         "queue": queue_info()}})
        if not self._guard():
            return None
        if route == API + "/info":
            return self._send(200, {"ok": True, "data": info()})
        if route == API + "/capabilities":
            cmds = [registry.public(e) for e in registry.all_commands().values()]
            return self._send(200, {"ok": True, "data": {"commandCount": len(cmds), "commands": cmds}})
        if route in (API + "/jobs/status", API + "/jobs/by-request"):
            query = parse_qs(url.query)
            try:
                wait = float((query.get("waitSec") or ["0"])[0] or 0)
            except ValueError:
                wait = 0.0
            if route.endswith("/by-request"):
                key = (query.get("requestId") or [""])[0]
                job = find_by_request(key) if key else None
                if not job:
                    return self._fail(404, "JOB_NOT_FOUND", "No job for request id %s." % key)
            else:
                key = (query.get("jobId") or [""])[0]
                with _state["lock"]:
                    job = _state["jobs"].get(key)
                if not job:
                    return self._fail(404, "JOB_NOT_FOUND", "No job %s." % key)
            if wait > 0 and job["state"] in ACTIVE_STATES:
                job["event"].wait(timeout=min(wait, 55.0))
            return self._send(200, {"ok": True, "data": _job_payload(job)})
        return self._fail(404, "NOT_FOUND", "Unknown route %s." % route)

    def do_POST(self):  # noqa: N802
        route = urlparse(self.path).path.rstrip("/")
        if not self._guard():
            return None
        try:
            body = self._body()
        except Exception as error:  # noqa: BLE001
            return self._fail(400, "BAD_REQUEST", str(error))
        if route == API + "/commands":
            command = body.get("command")
            if not isinstance(command, str) or not command.strip():
                return self._fail(400, "MISSING_COMMAND", "Body needs a non-empty 'command' string.")
            params = body.get("params") or {}
            if not isinstance(params, dict):
                return self._fail(400, "BAD_PARAMS", "'params' must be an object.")
            try:
                wait = float(body.get("waitSec", 25) or 0)
            except (TypeError, ValueError):
                return self._fail(400, "BAD_REQUEST", "'waitSec' must be a number.")
            job, duplicate = submit(command, params, wait, client=self._client(), request_id=self._request_id())
            return self._send(200, {"ok": True, "data": _job_payload(job, duplicate)})
        if route == API + "/jobs/cancel":
            job, error = cancel(body.get("jobId", ""))
            if error == "JOB_NOT_FOUND":
                return self._fail(404, "JOB_NOT_FOUND", "No such job.")
            if error:
                return self._fail(409, "JOB_NOT_CANCELLABLE", "Only queued jobs can be cancelled (state %s)." % job["state"])
            return self._send(200, {"ok": True, "data": _job_payload(job)})
        return self._fail(404, "NOT_FOUND", "Unknown route %s." % route)


# ------------------------------------------------------------------ lifecycle

def info():
    return {
        "app": "blender",
        "version": VERSION,
        "blenderVersion": bpy.app.version_string,
        "file": bpy.data.filepath or "",
        "port": _state["port"],
        "endpoint": endpoint(),
        "commandCount": len(registry.all_commands()),
        "pid": os.getpid(),
        "queue": queue_info(),
    }


def endpoint():
    return "http://127.0.0.1:%d%s" % (_state["port"], API) if _state["port"] else ""


def is_running():
    return _state["server"] is not None


def _heartbeat():
    if not is_running():
        return None
    try:
        instances.write_record({
            "app": "blender", "endpoint": endpoint(), "tokenFile": _state["token_file"],
            "version": VERSION, "document": bpy.data.filepath or "", "blenderVersion": bpy.app.version_string,
            "unattended": bool(bpy.app.background),  # a background Blender's exit is never a crash for the hub
        })
    except Exception:  # noqa: BLE001
        pass
    return 20.0


class _BridgeHTTPServer(ThreadingHTTPServer):
    """Localhost server that owns its port exclusively.

    ThreadingHTTPServer sets SO_REUSEADDR; on Windows that lets a second Blender bind the same port and
    steal requests meant for the first. There it is turned off and SO_EXCLUSIVEADDRUSE is set before bind,
    so the second bind fails and start() moves on to the next port."""

    daemon_threads = True
    allow_reuse_address = not sys.platform.startswith("win")
    allow_reuse_port = False

    def server_bind(self):
        if sys.platform.startswith("win"):
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                try:
                    self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
                except OSError:
                    pass
        super().server_bind()


def start(port=DEFAULT_PORT, port_range=50):
    if is_running():
        return _state["port"]
    last_error = None
    for candidate in range(int(port), int(port) + int(port_range)):
        try:
            httpd = _BridgeHTTPServer(("127.0.0.1", candidate), _Handler)
            break
        except OSError as error:
            last_error = error
    else:
        raise RuntimeError("No free localhost port in %d..%d (%s)" % (port, port + port_range - 1, last_error))
    httpd.daemon_threads = True
    _state["server"] = httpd
    _state["port"] = httpd.server_address[1]
    _state["token"] = secrets.token_hex(24)
    token_file = os.path.join(instances.instances_dir(), "blender-%d.token" % os.getpid())
    with open(token_file, "w", encoding="utf-8") as handle:
        handle.write(_state["token"])
    _state["token_file"] = token_file
    instances.remove_record_at_exit("blender")
    thread = threading.Thread(target=httpd.serve_forever, name="WildframeForgeBlenderHTTP", daemon=True)
    thread.start()
    _state["thread"] = thread
    _state["pump"] = True
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.05, persistent=True)
    if not bpy.app.timers.is_registered(_heartbeat):
        bpy.app.timers.register(_heartbeat, first_interval=0.1, persistent=True)
    try:  # a newly loaded .blend has a fresh undo stack
        if _on_load_post not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(_on_load_post)
    except Exception:  # noqa: BLE001
        pass
    return _state["port"]


def _on_load_post(*_args):
    _clear_undo_journal()


try:
    _on_load_post = bpy.app.handlers.persistent(_on_load_post)
except Exception:  # noqa: BLE001 - stubbed bpy in tests
    pass


def stop():
    _state["pump"] = False
    httpd = _state["server"]
    _state["server"] = None
    if httpd is not None:
        threading.Thread(target=httpd.shutdown, daemon=True).start()
        try:
            httpd.server_close()
        except Exception:  # noqa: BLE001
            pass
    for fn in (_pump, _heartbeat):
        try:
            if bpy.app.timers.is_registered(fn):
                bpy.app.timers.unregister(fn)
        except Exception:  # noqa: BLE001
            pass
    try:
        if _on_load_post in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_on_load_post)
    except Exception:  # noqa: BLE001
        pass
    instances.remove_record("blender")
    try:
        if _state["token_file"]:
            os.remove(_state["token_file"])
    except OSError:
        pass
    _state["port"] = 0
    _state["token"] = ""
    # fail anything still waiting so HTTP callers are released
    with _state["lock"]:
        for job in _state["jobs"].values():
            if job["state"] in ("QUEUED", "RUNNING"):
                _finish(job, registry.envelope(False, "BRIDGE_STOPPED", "The Blender bridge was stopped."))
        _state["queue"].clear()
        _state["active"] = None
    _clear_undo_journal()
