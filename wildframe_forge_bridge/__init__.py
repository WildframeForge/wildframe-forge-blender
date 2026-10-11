# SPDX-License-Identifier: GPL-3.0-or-later
"""Wildframe Forge Bridge for Blender.

Lets AI assistants (through the Wildframe Forge Bridge connector) and the Wildframe Forge Unreal plugin control Blender
over a token-protected localhost HTTP API, and moves assets between Blender and Unreal Engine.
"""

bl_info = {
    "name": "Wildframe Forge Bridge",
    "author": "Wildframe Forge",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > Wildframe Forge",
    "description": "Let AI assistants drive Blender and swap assets with Unreal Engine",
    "category": "Pipeline",
}

import bpy  # noqa: E402

from . import commands, mailbox, prefs, server, ui  # noqa: E402


def _autostart():
    # Background Blender (blender -b, render farms) is not a session anyone works in: no bridge, no record,
    # so its normal exit is never mistaken for a crash, and no mailbox imports into it.
    if bpy.app.background:
        return None
    try:
        if prefs.get().auto_start and not server.is_running():
            server.start(prefs.get().port)
    except Exception as error:  # noqa: BLE001 - never block Blender start-up
        print("Wildframe Forge Bridge: could not start:", error)
    return None


def register():
    bpy.utils.register_class(prefs.WildframeForgePreferences)
    for cls in ui.CLASSES:
        bpy.utils.register_class(cls)
    count = commands.load()
    print("Wildframe Forge Bridge: %d commands loaded" % count)
    # persistent: Blender drops non-persistent timers when it loads a .blend, which happens when it is
    # started by double-clicking a file - the bridge would then never start.
    bpy.app.timers.register(_autostart, first_interval=1.0, persistent=True)
    if bpy.app.background:
        return
    try:
        mailbox.start()
    except Exception as error:  # noqa: BLE001
        print("Wildframe Forge Bridge: mailbox disabled:", error)


def unregister():
    ui.free_icons()
    try:
        mailbox.stop()
    except Exception:  # noqa: BLE001
        pass
    try:
        server.stop()
    except Exception:  # noqa: BLE001
        pass
    for cls in reversed(ui.CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    try:
        bpy.utils.unregister_class(prefs.WildframeForgePreferences)
    except RuntimeError:
        pass
