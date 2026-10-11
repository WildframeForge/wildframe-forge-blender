# SPDX-License-Identifier: GPL-3.0-or-later
"""Discovery, editor state, undo, raw Python and file commands."""

import contextlib
import io
import os
import traceback

import bpy

from .. import ctx, prefs, registry
from ..registry import CommandError, command


@command("CORE.PING", "Check the Blender bridge answers. Returns app, versions and the open file.")
def ping(params):
    from .. import server
    return server.info()


@command("COMMAND.LIST", "List Blender bridge commands (names, family, description). Filter by family.",
         params={"family": {"type": "string", "description": "e.g. OBJECTS, IO, MATERIALS"}})
def list_commands(params):
    fam = (params.get("family") or "").upper()
    rows = [{"name": e["name"], "family": e["family"], "description": e["description"],
             "mutating": e["mutating"], "destructive": e["destructive"]}
            for e in registry.all_commands().values() if not fam or e["family"] == fam]
    families = sorted({e["family"] for e in registry.all_commands().values()})
    return {"count": len(rows), "families": families, "commands": sorted(rows, key=lambda r: r["name"])}


@command("COMMAND.SEARCH", "Search Blender bridge commands by words (name and description).",
         params={"query": {"type": "string"}, "limit": {"type": "integer", "default": 20}}, required=["query"])
def search_commands(params):
    words = [w for w in params["query"].lower().split() if w]
    scored = []
    for e in registry.all_commands().values():
        text = (e["name"] + " " + e["description"]).lower()
        score = sum(text.count(w) for w in words) + sum(3 for w in words if w in e["name"].lower())
        if score:
            scored.append((score, e))
    scored.sort(key=lambda t: -t[0])
    return {"commands": [{"name": e["name"], "description": e["description"]} for _, e in scored[:params["limit"]]]}


@command("COMMAND.DESCRIBE", "Full description, parameter schema and examples of one Blender command.",
         params={"command": {"type": "string"}}, required=["command"])
def describe(params):
    entry = registry.all_commands().get(params["command"].strip().upper())
    if not entry:
        raise CommandError("UNKNOWN_COMMAND", "No Blender command %s." % params["command"])
    return registry.public(entry)


@command("EDITOR.UNDO", "Undo the last step(s) in Blender. Several AI clients can share this Blender: undoing a "
         "step another client made is refused (UNDO_OTHER_CLIENT) unless force=true.",
         params={"steps": {"type": "integer", "default": 1},
                 "force": {"type": "boolean", "default": False,
                           "description": "Undo even if the step(s) were made by another AI client"}},
         mutating=False)
def undo(params):
    from .. import server
    steps = max(1, min(params["steps"], 50))
    taking = server.check_undo(steps, force=params["force"])
    done = 0
    with ctx.view3d():
        for _ in range(steps):
            if bpy.ops.ed.undo.poll():
                bpy.ops.ed.undo()
                done += 1
    server.note_undone(done)
    out = {"undone": done}
    if taking:
        out["steps"] = taking[:done]
    return out


@command("EDITOR.REDO", "Redo step(s) in Blender.", params={"steps": {"type": "integer", "default": 1}})
def redo(params):
    from .. import server
    done = 0
    with ctx.view3d():
        for _ in range(max(1, min(params["steps"], 50))):
            if bpy.ops.ed.redo.poll():
                bpy.ops.ed.redo()
                done += 1
    server.note_redone(done)
    return {"redone": done}


@command("PYTHON.EXECUTE",
         "Run Blender Python (bpy) code on the main thread. print() output is returned; set a variable named "
         "'result' to return data. Requires confirm=true and 'Allow raw Python' in the add-on preferences.",
         params={"code": {"type": "string"}, "confirm": {"type": "boolean", "default": False}},
         required=["code"], mutating=True, destructive=True)
def python_execute(params):
    if not prefs.get().allow_python:
        raise CommandError("PYTHON_DISABLED", "Raw Python is turned off in the Wildframe Forge Bridge add-on preferences.")
    if not params["confirm"]:
        raise CommandError("CONFIRM_REQUIRED", "PYTHON.EXECUTE runs arbitrary code: pass confirm=true.")
    out = io.StringIO()
    scope = {"bpy": bpy, "__name__": "__wildframe__"}
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), ctx.view3d():
            exec(compile(params["code"], "<wildframe>", "exec"), scope)  # noqa: S102 - explicit, confirmed, opt-in
    except Exception as error:  # noqa: BLE001
        raise CommandError("PYTHON_ERROR", "%s: %s" % (type(error).__name__, error),
                           {"output": out.getvalue()[-16000:], "traceback": traceback.format_exc()[-6000:]})
    return {"output": out.getvalue()[-16000:], "result": ctx.jsonable(scope.get("result"))}


@command("FILE.OPEN", "Open a .blend file (unsaved changes are lost unless save_first=true).",
         params={"path": {"type": "string"}, "save_first": {"type": "boolean", "default": False}},
         required=["path"], mutating=True, destructive=True)
def file_open(params):
    path = os.path.abspath(params["path"])
    if not os.path.isfile(path):
        raise CommandError("FILE_NOT_FOUND", "No file at %s." % path)
    if params["save_first"] and bpy.data.filepath:
        bpy.ops.wm.save_mainfile()
    bpy.ops.wm.open_mainfile(filepath=path)
    return {"file": bpy.data.filepath}


@command("FILE.SAVE", "Save the current .blend (optionally to a new path).",
         params={"path": {"type": "string", "description": "Save As path; omit to save in place."},
                 "copy": {"type": "boolean", "default": False, "description": "Save a copy, keep the current file open."}},
         mutating=True)
def file_save(params):
    path = params.get("path")
    if path:
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if params["copy"]:
            bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        else:
            bpy.ops.wm.save_as_mainfile(filepath=path)
    else:
        if not bpy.data.filepath:
            raise CommandError("NO_FILE_PATH", "This scene was never saved: pass path.")
        bpy.ops.wm.save_mainfile()
    return {"file": bpy.data.filepath, "savedTo": path or bpy.data.filepath}


@command("FILE.NEW", "Start a new empty scene (factory startup objects removed unless keep_default=true).",
         params={"keep_default": {"type": "boolean", "default": False}}, mutating=True, destructive=True)
def file_new(params):
    bpy.ops.wm.read_homefile(use_empty=not params["keep_default"])
    return {"objects": len(bpy.data.objects)}


@command("SCENE.INFO", "Summary of the current scene: file, units, frame range, render engine, object counts, "
         "selection and active object.")
def scene_info(params):
    scene = bpy.context.scene
    counts = {}
    for obj in scene.objects:
        counts[obj.type] = counts.get(obj.type, 0) + 1
    active = bpy.context.view_layer.objects.active
    return {
        "file": bpy.data.filepath,
        "dirty": bpy.data.is_dirty,
        "scene": scene.name,
        "scenes": [s.name for s in bpy.data.scenes],
        "unitSystem": scene.unit_settings.system,
        "unitScale": scene.unit_settings.scale_length,
        "frameStart": scene.frame_start,
        "frameEnd": scene.frame_end,
        "frameCurrent": scene.frame_current,
        "fps": scene.render.fps / scene.render.fps_base,
        "renderEngine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "objectCounts": counts,
        "objectTotal": len(scene.objects),
        "selected": [o.name for o in bpy.context.selected_objects][:200],
        "active": active.name if active else None,
        "collections": [c.name for c in bpy.data.collections][:200],
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
        "actions": len(bpy.data.actions),
    }


@command("SCENE.SET", "Change scene settings: frame range, current frame, fps, unit scale, render engine, resolution.",
         params={"frame_start": {"type": "integer"}, "frame_end": {"type": "integer"},
                 "frame_current": {"type": "integer"}, "fps": {"type": "integer"},
                 "unit_scale": {"type": "number"},
                 "render_engine": {"type": "string", "enum": ctx.ENGINE_NAMES},
                 "resolution": {"type": "array"}}, mutating=True)
def scene_set(params):
    scene = bpy.context.scene
    if "frame_start" in params:
        scene.frame_start = params["frame_start"]
    if "frame_end" in params:
        scene.frame_end = params["frame_end"]
    if "frame_current" in params:
        scene.frame_set(params["frame_current"])
    if "fps" in params:
        scene.render.fps = params["fps"]
        scene.render.fps_base = 1.0
    if "unit_scale" in params:
        scene.unit_settings.scale_length = params["unit_scale"]
    if "render_engine" in params:
        ctx.set_engine(scene, params["render_engine"])
    if "resolution" in params:
        w, h = params["resolution"][:2]
        scene.render.resolution_x, scene.render.resolution_y = int(w), int(h)
    return scene_info({})
