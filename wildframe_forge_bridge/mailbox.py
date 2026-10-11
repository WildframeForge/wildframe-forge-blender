# SPDX-License-Identifier: GPL-3.0-or-later
"""Delivery mailbox, Blender side.

A package sent from Unreal while Blender was closed waits in the exchange folder with status "waiting".
This timer imports such packages into the open .blend (one at a time, a few seconds after start-up and
after each file load), marks them imported or failed, and restarts the Wildframe Forge Hub if it stopped.
"""

import os

import bpy

from . import exchange, prefs, registry

_state = {"hub_checked": 0.0, "reported": set()}
CHECK_EVERY = 20.0


def _root():
    try:
        return prefs.get().exchange_dir or None
    except Exception:  # noqa: BLE001
        return None


def deliver_one():
    waiting = exchange.waiting_packages("blender", _root())
    # another Blender may be importing the same package: take the first one this process can claim
    pkg = next((w for w in waiting if exchange.claim_delivery(w["folder"])), None)
    if pkg is None:
        return None
    try:
        params = dict(pkg["options"] or {})
        params["package"] = pkg["folder"]
        reply = registry.run("BRIDGE.RECEIVE", params)
        doc = bpy.data.filepath or "(unsaved file)"
        if reply.get("ok"):
            exchange.mark_delivery(pkg["folder"], "imported", app="blender", document=doc)
            print("Wildframe Forge mailbox: imported %s from %s" % (", ".join(pkg["items"][:5]) or os.path.basename(pkg["folder"]),
                                                                   pkg.get("source") or "another app"))
        else:
            exchange.mark_delivery(pkg["folder"], "failed", app="blender", document=doc,
                                   error=reply.get("message") or reply.get("code"))
            print("Wildframe Forge mailbox: could not import %s: %s" % (os.path.basename(pkg["folder"]), reply.get("message")))
    finally:
        exchange.release_delivery(pkg["folder"])
    return reply


def _tick():
    try:
        import time
        now = time.time()
        if now - _state["hub_checked"] > 60:
            _state["hub_checked"] = now
            exchange.ensure_hub()
        if exchange.hub_settings().get("autoImport", True):
            if deliver_one() is not None:
                return 2.0  # more may be waiting
        else:
            waiting = exchange.waiting_packages("blender", _root())
            new = [w["folder"] for w in waiting if w["folder"] not in _state["reported"]]
            if new:
                _state["reported"].update(new)
                print("Wildframe Forge mailbox: %d delivery(s) waiting for Blender (auto-import is off)." % len(waiting))
    except Exception as error:  # noqa: BLE001 - never break Blender
        print("Wildframe Forge mailbox: check failed:", error)
    return CHECK_EVERY


@bpy.app.handlers.persistent
def _on_load(_dummy):
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    bpy.app.timers.register(_tick, first_interval=5.0, persistent=True)


def start():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=8.0, persistent=True)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def stop():
    try:
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
    except Exception:  # noqa: BLE001
        pass
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
