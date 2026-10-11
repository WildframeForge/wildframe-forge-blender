# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers shared by commands: context overrides, object lookup, value conversion."""

import contextlib

import bpy
import mathutils

from .registry import CommandError


def view3d_override():
    """Keyword arguments for ``bpy.context.temp_override`` pointing at a 3D viewport (or {})."""
    wm = bpy.context.window_manager
    for window in (wm.windows if wm else []):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                return {"window": window, "screen": window.screen, "area": area, "region": region}
    return {}


@contextlib.contextmanager
def view3d():
    override = view3d_override()
    if override:
        with bpy.context.temp_override(**override):
            yield override
    else:
        yield {}


@contextlib.contextmanager
def object_mode():
    """Make sure we are in Object mode for operators that need it, restore afterwards."""
    obj = bpy.context.view_layer.objects.active
    previous = obj.mode if obj else "OBJECT"
    if obj and previous != "OBJECT":
        with view3d():
            bpy.ops.object.mode_set(mode="OBJECT")
    try:
        yield
    finally:
        if obj and previous != "OBJECT" and obj.name in bpy.data.objects:
            try:
                with view3d():
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode=previous)
            except Exception:  # noqa: BLE001
                pass


def get_object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        similar = [o.name for o in bpy.data.objects if name.lower() in o.name.lower()][:10]
        raise CommandError("OBJECT_NOT_FOUND", "No object named '%s'." % name, {"similar": similar})
    return obj


def get_objects(names):
    return [get_object(n) for n in names]


def select_only(objects, active=None):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        try:
            obj.select_set(True)
        except RuntimeError:
            pass  # object not in the view layer
    if objects:
        bpy.context.view_layer.objects.active = active or objects[0]


def vec(value, size=3, name="value"):
    if value is None:
        return None
    if isinstance(value, dict):
        keys = ("x", "y", "z", "w")[:size]
        value = [value.get(k, 0.0) for k in keys]
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise CommandError("BAD_PARAM_VALUE", "'%s' must be a list of %d numbers." % (name, size))
    return [float(v) for v in value]


def to_list(value, digits=5):
    try:
        return [round(float(v), digits) for v in value]
    except TypeError:
        return value


def jsonable(value, depth=0):
    """Convert Blender values (vectors, colors, ID blocks, ...) to JSON-friendly data."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (mathutils.Vector, mathutils.Color, mathutils.Euler, mathutils.Quaternion)):
        return to_list(value)
    if isinstance(value, mathutils.Matrix):
        return [to_list(row) for row in value]
    if isinstance(value, bpy.types.ID):
        return {"type": type(value).__name__, "name": value.name}
    if depth < 2 and isinstance(value, (list, tuple)):
        return [jsonable(v, depth + 1) for v in value]
    try:
        if depth < 2 and len(value) <= 64:
            return [jsonable(v, depth + 1) for v in value]
    except TypeError:
        pass
    return str(value)


def object_summary(obj, detail=False):
    out = {
        "name": obj.name,
        "type": obj.type,
        "location": to_list(obj.location),
        "rotationEuler": to_list(obj.rotation_euler),
        "scale": to_list(obj.scale),
        "parent": obj.parent.name if obj.parent else None,
        "visible": obj.visible_get() if obj.name in bpy.context.view_layer.objects else False,
        "collections": [c.name for c in obj.users_collection],
    }
    if obj.type == "MESH" and obj.data:
        out["mesh"] = {"name": obj.data.name, "vertices": len(obj.data.vertices), "polygons": len(obj.data.polygons)}
        out["materials"] = [slot.material.name if slot.material else None for slot in obj.material_slots]
    if detail:
        out["dimensions"] = to_list(obj.dimensions)
        out["modifiers"] = [{"name": m.name, "type": m.type, "show_viewport": m.show_viewport} for m in obj.modifiers]
        out["children"] = [c.name for c in obj.children]
        out["customProperties"] = {k: jsonable(obj[k]) for k in obj.keys() if not k.startswith("_")}
        out["worldMatrix"] = jsonable(obj.matrix_world)
        if obj.animation_data and obj.animation_data.action:
            out["action"] = obj.animation_data.action.name
        if obj.type in ("LIGHT", "CAMERA") and obj.data:
            out["data"] = {"name": obj.data.name, "type": getattr(obj.data, "type", obj.type)}
    return out


def set_path(target, path, value):
    """Set ``a.b.c`` on ``target`` (object, data, modifier...). Returns the new value as JSON."""
    parts = path.split(".")
    owner = target
    for part in parts[:-1]:
        if "[" in part and part.endswith("]"):
            base, index = part[:-1].split("[", 1)
            container = getattr(owner, base)
            owner = container[int(index)] if index.lstrip("-").isdigit() else container[index.strip("'\"")]
        else:
            owner = getattr(owner, part)
    attr = parts[-1]
    if not hasattr(owner, attr):
        raise CommandError("PROPERTY_NOT_FOUND", "'%s' has no property '%s'." % (type(owner).__name__, attr))
    current = getattr(owner, attr)
    if isinstance(current, (mathutils.Vector, mathutils.Color, mathutils.Euler)) and isinstance(value, (list, tuple)):
        value = type(current)(value) if not isinstance(current, mathutils.Euler) else mathutils.Euler(value, current.order)
    setattr(owner, attr, value)
    return jsonable(getattr(owner, attr))


ENGINE_NAMES = ["EEVEE", "CYCLES", "WORKBENCH", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"]


def set_engine(scene, name):
    """Set the render engine from a friendly or version-specific name (EEVEE was BLENDER_EEVEE_NEXT in 4.2-4.5).

    The engine list Blender reports (bl_rna enum_items) is incomplete in some builds (only EEVEE shows), so try
    the candidates directly instead of trusting that list.
    """
    wanted = str(name).upper()
    if "EEVEE" in wanted:
        candidates = [wanted, "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"]
    elif "WORKBENCH" in wanted:
        candidates = [wanted, "BLENDER_WORKBENCH"]
    else:
        candidates = [wanted]
    for ident in dict.fromkeys(candidates):
        try:
            scene.render.engine = ident
            return ident
        except (TypeError, ValueError):
            continue
    raise CommandError("BAD_ENGINE", "Unknown render engine %r. Use EEVEE, CYCLES or WORKBENCH." % name)
