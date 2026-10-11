# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender <-> Unreal exchange: shared package folder and a small client for the Unreal bridge.

Package layout (both apps write and read the same format):

    <state>/Exchange/<timestamp>-<source>-<id>/
        package.json            WILDFRAME_EXCHANGE_V1 manifest
        <asset files>           .fbx / .glb / .obj / .usd / textures

    {"schema": "WILDFRAME_EXCHANGE_V1", "id": "...", "source": "blender", "target": "unreal",
     "created": "2026-10-07T12:00:00Z", "units": "meters" | "centimeters", "upAxis": "Z",
     "items": [{"file": "Crate.fbx", "name": "Crate", "kind": "static_mesh" | "skeletal_mesh" |
                "animation" | "scene" | "texture", "format": "fbx"}],
     "destination": "/Game/FromBlender"}
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

from . import instances
from .registry import CommandError

SCHEMA = "WILDFRAME_EXCHANGE_V1"


def exchange_root(custom=None):
    root = custom or os.path.join(instances.state_dir(), "Exchange")
    os.makedirs(root, exist_ok=True)
    return root


def new_package_dir(source, root=None):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(exchange_root(root), "%s-%s-%s" % (stamp, source, uuid.uuid4().hex[:6]))
    os.makedirs(path, exist_ok=True)
    return path


def write_manifest(folder, manifest):
    manifest = dict(manifest)
    manifest.setdefault("schema", SCHEMA)
    manifest.setdefault("id", os.path.basename(folder))
    manifest.setdefault("created", instances.now_iso())
    path = os.path.join(folder, "package.json")
    # atomic: the hub and Unreal may read the manifest while it is being written
    return instances.atomic_write_json(path, manifest)


def read_manifest(path):
    if os.path.isdir(path):
        path = os.path.join(path, "package.json")
    if not os.path.isfile(path):
        raise CommandError("PACKAGE_NOT_FOUND", "No exchange package at %s." % path)
    with open(path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("schema") != SCHEMA:
        raise CommandError("BAD_PACKAGE", "%s is not a %s manifest." % (path, SCHEMA))
    manifest["_folder"] = os.path.dirname(os.path.abspath(path))
    return manifest


def list_packages(root=None, limit=20):
    root = exchange_root(root)
    out = []
    for name in sorted(os.listdir(root), reverse=True)[: max(1, limit) * 3]:
        manifest = os.path.join(root, name, "package.json")
        if os.path.isfile(manifest):
            try:
                with open(manifest, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                out.append({"folder": os.path.join(root, name), "source": data.get("source"),
                            "target": data.get("target"), "created": data.get("created"),
                            "items": [i.get("name") for i in data.get("items", [])]})
            except Exception:  # noqa: BLE001
                continue
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ Unreal client


def _transfer_client():
    """Client id sent to Unreal for a transfer: the AI client whose bridge job is running it, so the user's own
    undo in Unreal is not refused as "another AI agent's" step; "blender#<pid>" when no bridge job is running
    (UI button, mailbox)."""
    try:
        from . import server  # late import: server imports bpy and is only present inside Blender
        client = server.current_client()
        if client and client != server.UNKNOWN_CLIENT:
            return client
    except Exception:  # noqa: BLE001
        pass
    return "blender#%d" % os.getpid()


class UnrealClient:
    """Talks to the Wildframe Forge Unreal live bridge (same protocol the AI connector uses)."""

    def __init__(self, record):
        self.record = record
        self.endpoint = record["endpoint"].rstrip("/")
        self.token = instances.read_token(record)
        # Captured now, on the main thread while the bridge job is active: transfers finish on a background
        # thread, where no job is "current" any more.
        self.client_id = _transfer_client()

    @classmethod
    def find(cls, project=None):
        records = instances.list_instances("unreal")
        if project:
            # Same project whether it is written with \ or / (the AI connector passes Windows paths).
            norm = lambda s: (s or "").replace("\\", "/").lower()
            key = norm(project)
            records = [r for r in records if key in norm(r.get("document")) or key in norm(r.get("project"))]
        if not records:
            raise CommandError("UNREAL_NOT_RUNNING",
                               "No Unreal editor with Wildframe Forge Bridge is running%s. Open your project in Unreal "
                               "(the plugin registers itself), then try again." % (" for '%s'" % project if project else ""))
        return cls(records[0])

    def _request(self, method, route, body=None, timeout=30.0):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.endpoint + route, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Wildframe-Request-Id", str(uuid.uuid4()))
        req.add_header("X-Wildframe-Client", getattr(self, "client_id", None) or _transfer_client())
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            try:
                return json.loads(error.read().decode("utf-8"))
            except Exception:  # noqa: BLE001
                raise CommandError("UNREAL_HTTP_%d" % error.code, str(error))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise CommandError("UNREAL_UNREACHABLE", "Unreal bridge at %s did not answer: %s" % (self.endpoint, error))

    def run(self, command, params, timeout_sec=600.0):
        """Submit a command and wait until it finishes. Returns the first operation result."""
        submitted = self._request("POST", "/commands", {"command": command, "params": params or {}})
        job = (submitted.get("data") or {}).get("job") or submitted.get("data") or {}
        job_id = job.get("jobId") or job.get("id")
        if not job_id:
            raise CommandError("UNREAL_REJECTED", "Unreal refused %s." % command, {"response": submitted})
        deadline = time.time() + timeout_sec
        delay = 0.25
        while True:
            status = self._request("GET", "/jobs/status?jobId=" + job_id, timeout=15.0)
            job = (status.get("data") or {}).get("job") or status.get("data") or {}
            state = str(job.get("state") or job.get("status") or "").upper()
            if state in ("COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED"):
                results = job.get("results") or []
                first = results[0] if results else {}
                return {"state": state, "jobId": job_id, "ok": state.startswith("COMPLETED"),
                        "code": first.get("code"), "message": first.get("message"), "data": first.get("data", {})}
            if time.time() > deadline:
                return {"state": state or "UNKNOWN", "jobId": job_id, "ok": False,
                        "message": "Still running in Unreal after %d s; check it there." % timeout_sec}
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)


# ------------------------------------------------------------------ delivery mailbox (same format as Unreal's xapp.py)

def last_seen(app):
    """The document an app last had open (written by that app: Unreal records its .uproject), or ""."""
    try:
        with open(os.path.join(instances.state_dir(), "LastSeen", "%s.json" % app), "r", encoding="utf-8") as handle:
            return json.load(handle).get("document") or ""
    except Exception:  # noqa: BLE001
        return ""


def mark_delivery(folder, status, **info):
    """Set the delivery block of a package: status waiting | imported | failed."""
    path = os.path.join(folder, "package.json")
    with open(path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    d = dict(manifest.get("delivery") or {})
    d["status"] = status
    if status == "waiting":
        d.setdefault("queued", instances.now_iso())
        d.pop("error", None)
    elif status == "imported":
        d["importedAt"] = instances.now_iso()
        d.pop("error", None)
    elif status == "failed":
        d["attempts"] = int(d.get("attempts") or 0) + 1
        d["error"] = str(info.get("error") or "Import failed")[:500]
    if info.get("app") or info.get("document"):
        d["importedBy"] = {"app": info.get("app"), "document": info.get("document")}
    if info.get("for_document"):
        d["forDocument"] = info["for_document"]
    if info.get("options") is not None:
        manifest["deliveryOptions"] = info["options"]
    manifest["delivery"] = d
    instances.atomic_write_json(path, manifest)  # unique temp name: the hub writes this file too
    return d


CLAIM_FILE = ".import-claim.lock"
CLAIM_STALE_SEC = 900


def claim_delivery(folder, stale_sec=CLAIM_STALE_SEC):
    """Claim a waiting package so only one process imports it (two Blenders can both see it waiting).

    Creates ``<folder>/.import-claim.lock`` exclusively; a claim older than ``stale_sec`` (crashed importer) is
    taken over. Returns True when this process holds the claim and the package is still waiting."""
    lock = os.path.join(folder, CLAIM_FILE)
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > stale_sec:
                    os.remove(lock)
                    continue
            except OSError:
                pass
            return False
        except OSError:
            return False
        with os.fdopen(fd, "w") as handle:
            handle.write("%d %s" % (os.getpid(), instances.now_iso()))
        break
    else:
        return False
    try:
        with open(os.path.join(folder, "package.json"), "r", encoding="utf-8") as handle:
            still = (json.load(handle).get("delivery") or {}).get("status") == "waiting"
    except Exception:  # noqa: BLE001
        still = False
    if not still:
        release_delivery(folder)
    return still


def release_delivery(folder):
    try:
        os.remove(os.path.join(folder, CLAIM_FILE))
    except OSError:
        pass


def waiting_packages(target, root=None):
    root = exchange_root(root)
    out = []
    for name in sorted(os.listdir(root)):
        manifest = os.path.join(root, name, "package.json")
        if not os.path.isfile(manifest):
            continue
        try:
            with open(manifest, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:  # noqa: BLE001
            continue
        if data.get("target") == target and (data.get("delivery") or {}).get("status") == "waiting":
            out.append({"folder": os.path.join(root, name), "options": data.get("deliveryOptions") or {},
                        "source": data.get("source"), "items": [i.get("name") for i in data.get("items", [])],
                        "forDocument": (data.get("delivery") or {}).get("forDocument") or ""})
    return out


HUB_PORT = 47811


def hub_settings():
    try:
        with open(os.path.join(instances.state_dir(), "Hub", "settings.json"), "r", encoding="utf-8-sig") as handle:
            return dict({"autoImport": True}, **json.load(handle))
    except Exception:  # noqa: BLE001
        return {"autoImport": True}


def hub_running(timeout=0.4):
    req = urllib.request.Request("http://127.0.0.1:%d/status" % HUB_PORT, headers={"x-wfab-client": "app"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return bool(json.loads(resp.read().decode("utf-8") or "{}").get("hub"))
    except Exception:  # noqa: BLE001
        return False


def ensure_hub():
    """Start the Wildframe Forge Hub from <state>/Hub/launch.json if it is not running."""
    if hub_running():
        return True
    try:
        with open(os.path.join(instances.state_dir(), "Hub", "launch.json"), "r", encoding="utf-8-sig") as handle:
            launch = json.load(handle)
    except Exception:  # noqa: BLE001
        return False
    node, script = launch.get("node"), launch.get("hub")
    if not (node and script and os.path.isfile(node) and os.path.isfile(script)):
        return False
    import subprocess
    import sys
    flags = 0x00000008 | 0x00000200 | 0x08000000 if sys.platform.startswith("win") else 0
    try:
        subprocess.Popen([node, script], creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:  # noqa: BLE001
        return False
