# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendering, viewport capture and keyframe animation."""

import os
import tempfile
import time
import uuid

import bpy

from .. import ctx
from ..registry import CommandError, command


TEMP_KEEP_SEC = 24 * 3600


def _default_png(stem):
    """A fresh image path per call: several AI clients share this Blender (and other Blenders share the temp
    folder), so a fixed name would let one client's capture overwrite the image another is about to read."""
    folder = os.path.join(tempfile.gettempdir(), "WildframeForge", "Blender")
    os.makedirs(folder, exist_ok=True)
    _prune(folder)
    return os.path.join(folder, "%s-%d-%s.png" % (stem, os.getpid(), uuid.uuid4().hex[:10]))


def _prune(folder, keep_sec=TEMP_KEEP_SEC):
    """Remove our own default captures older than a day so unique names do not pile up."""
    cutoff = time.time() - keep_sec
    try:
        for name in os.listdir(folder):
            if not name.endswith(".png"):
                continue
            path = os.path.join(folder, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                continue
    except OSError:
        pass


@command("RENDER.STILL", "Render the active camera to an image file (PNG/JPEG/EXR by extension). Optional "
         "resolution, samples and engine override for this render only. Long renders keep running; poll the job.",
         params={"path": {"type": "string"}, "resolution": {"type": "array"}, "samples": {"type": "integer"},
                 "engine": {"type": "string", "enum": ctx.ENGINE_NAMES},
                 "frame": {"type": "integer"}}, long_running=True)
def render_still(params):
    scene = bpy.context.scene
    if scene.camera is None:
        raise CommandError("NO_CAMERA", "The scene has no active camera (CAMERAS.CREATE or CAMERAS.SET_ACTIVE).")
    path = os.path.abspath(params.get("path") or _default_png("render"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    saved = {"x": scene.render.resolution_x, "y": scene.render.resolution_y, "pct": scene.render.resolution_percentage,
             "engine": scene.render.engine, "fmt": scene.render.image_settings.file_format}
    try:
        if params.get("resolution"):
            scene.render.resolution_x, scene.render.resolution_y = [int(v) for v in params["resolution"][:2]]
            scene.render.resolution_percentage = 100
        if params.get("engine"):
            ctx.set_engine(scene, params["engine"])
        if params.get("samples"):
            if scene.render.engine == "CYCLES":
                scene.cycles.samples = params["samples"]
            elif hasattr(scene, "eevee"):
                scene.eevee.taa_render_samples = params["samples"]
        if params.get("frame") is not None:
            scene.frame_set(params["frame"])
        ext = os.path.splitext(path)[1].lower()
        scene.render.image_settings.file_format = {".jpg": "JPEG", ".jpeg": "JPEG", ".exr": "OPEN_EXR"}.get(ext, "PNG")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
    finally:
        scene.render.resolution_x, scene.render.resolution_y = saved["x"], saved["y"]
        scene.render.resolution_percentage = saved["pct"]
        scene.render.engine = saved["engine"]
        scene.render.image_settings.file_format = saved["fmt"]
    return {"path": path, "exists": os.path.isfile(path)}


@command("VIEWPORT.SCREENSHOT", "Capture what the 3D viewport shows (fast OpenGL render) to a PNG. shading "
         "MATERIAL shows textures/materials, RENDERED the render engine; the viewport's own mode is restored after.",
         params={"path": {"type": "string"}, "use_camera": {"type": "boolean", "default": False},
                 "shading": {"type": "string", "enum": ["CURRENT", "SOLID", "MATERIAL", "RENDERED"],
                             "default": "CURRENT"}})
def viewport_screenshot(params):
    path = os.path.abspath(params.get("path") or _default_png("viewport"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    override = ctx.view3d_override()
    if not override:
        raise CommandError("NO_VIEWPORT", "No 3D viewport is open (Blender running in background?).")
    space = override["area"].spaces.active
    previous = space.shading.type
    try:
        if params["shading"] != "CURRENT":
            space.shading.type = params["shading"]
        with bpy.context.temp_override(**override):
            bpy.ops.render.opengl(view_context=not params["use_camera"])
    finally:
        space.shading.type = previous
    image = bpy.data.images.get("Render Result")
    if image is None:
        raise CommandError("CAPTURE_FAILED", "Viewport render produced no image.")
    image.save_render(path)
    return {"path": path, "exists": os.path.isfile(path)}


@command("VIEWPORT.FRAME", "Point the 3D viewport at objects (like numpad '.') or everything.",
         params={"names": {"type": "array", "default": []}})
def viewport_frame(params):
    override = ctx.view3d_override()
    if not override:
        raise CommandError("NO_VIEWPORT", "No 3D viewport is open.")
    with bpy.context.temp_override(**override):
        if params["names"]:
            ctx.select_only(ctx.get_objects(params["names"]))
            bpy.ops.view3d.view_selected()
        else:
            bpy.ops.view3d.view_all()
    return {"framed": params["names"] or "all"}


@command("VIEWPORT.SET_SHADING", "Set how the 3D viewports draw the scene: SOLID, MATERIAL (textures and materials), "
         "RENDERED (the render engine) or WIREFRAME. Viewport display only; the scene and its render settings are "
         "unchanged. Optional overlays/gizmos on or off, e.g. for a clean recording.",
         params={"shading": {"type": "string", "enum": ["SOLID", "MATERIAL", "RENDERED", "WIREFRAME"]},
                 "overlays": {"type": "boolean"}, "gizmos": {"type": "boolean"},
                 "all_viewports": {"type": "boolean", "default": True}},
         required=["shading"])
def viewport_set_shading(params):
    spaces = []
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                spaces.append(area.spaces.active)
    if not spaces:
        raise CommandError("NO_VIEWPORT", "No 3D viewport is open (Blender running in background?).")
    if not params["all_viewports"]:
        override = ctx.view3d_override()
        spaces = [override["area"].spaces.active] if override else spaces[:1]
    for space in spaces:
        space.shading.type = params["shading"]
        if params.get("overlays") is not None:
            space.overlay.show_overlays = bool(params["overlays"])
        if params.get("gizmos") is not None:
            space.show_gizmo = bool(params["gizmos"])
    first = spaces[0]
    return {"shading": first.shading.type, "overlays": first.overlay.show_overlays, "gizmos": first.show_gizmo,
            "viewports": len(spaces)}


@command("ANIMATION.INSERT_KEYFRAME", "Insert a keyframe on an object property (location, rotation_euler, scale, or "
         "any animatable path), optionally setting the value first. Rotation values are in radians.",
         params={"name": {"type": "string"}, "data_path": {"type": "string", "default": "location"},
                 "frame": {"type": "integer"}, "value": {}, "index": {"type": "integer", "default": -1}},
         required=["name", "frame"], mutating=True)
def insert_keyframe(params):
    obj = ctx.get_object(params["name"])
    if "value" in params and params["value"] is not None:
        ctx.set_path(obj, params["data_path"], params["value"])
    ok = obj.keyframe_insert(data_path=params["data_path"], frame=params["frame"], index=params["index"])
    if not ok:
        raise CommandError("KEYFRAME_FAILED", "Could not key %s.%s." % (obj.name, params["data_path"]))
    return {"name": obj.name, "action": obj.animation_data.action.name if obj.animation_data and obj.animation_data.action else None}


@command("ANIMATION.LIST_ACTIONS", "List actions (animations) with frame ranges and users.")
def list_actions(params):
    return {"actions": [{"name": a.name, "frameRange": ctx.to_list(a.frame_range), "users": a.users,
                         "fcurves": len(getattr(a, "fcurves", []) or [])} for a in bpy.data.actions]}


@command("ANIMATION.CLEAR", "Remove all animation from objects.", params={"names": {"type": "array"}},
         required=["names"], mutating=True, destructive=True)
def clear_animation(params):
    for obj in ctx.get_objects(params["names"]):
        obj.animation_data_clear()
    return {"cleared": params["names"]}
