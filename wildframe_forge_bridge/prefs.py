# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on preferences (Edit > Preferences > Add-ons > Wildframe Forge Bridge)."""

import bpy

ADDON_ID = __package__


def get():
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else _Defaults()


class _Defaults:
    port = 19950
    auto_start = True
    allow_python = False
    exchange_dir = ""
    default_destination = "/Game/FromBlender"
    default_format = "fbx"


def _restart(self, context):
    from . import server
    if server.is_running():
        server.stop()
        server.start(self.port)


class WildframeForgePreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    port: bpy.props.IntProperty(name="Port", default=19950, min=1024, max=65000,
                                description="First localhost port to try (the next free one is used)",
                                update=_restart)
    auto_start: bpy.props.BoolProperty(name="Start bridge with Blender", default=True)
    allow_python: bpy.props.BoolProperty(
        name="Allow raw Python (PYTHON.EXECUTE)", default=False,
        description="Lets connected AI tools run arbitrary Python in Blender. Only enable if you trust them")
    exchange_dir: bpy.props.StringProperty(
        name="Exchange folder", subtype="DIR_PATH", default="",
        description="Where transfer packages are written (empty = %LOCALAPPDATA%/WildframeForge/Exchange)")
    default_destination: bpy.props.StringProperty(name="Unreal destination", default="/Game/FromBlender")
    default_format: bpy.props.EnumProperty(name="Transfer format", default="fbx",
                                           items=[("fbx", "FBX", "Best for rigs and animation"),
                                                  ("glb", "glTF (GLB)", "Clean PBR materials for static meshes")])

    def draw(self, context):
        layout = self.layout
        from . import server
        row = layout.row()
        row.label(text="Bridge: %s" % (("running on port %d" % server._state["port"]) if server.is_running() else "stopped"),
                  icon="CHECKMARK" if server.is_running() else "X")
        row.operator("wildframe.open_setup", text="Open Setup (Blender, AI apps)", icon="PREFERENCES")
        layout.prop(self, "auto_start")
        layout.prop(self, "port")
        layout.prop(self, "exchange_dir")
        layout.prop(self, "default_destination")
        layout.prop(self, "default_format")
        box = layout.box()
        box.prop(self, "allow_python")
        box.label(text="Only local apps holding this session's token can connect (127.0.0.1).", icon="LOCKED")
