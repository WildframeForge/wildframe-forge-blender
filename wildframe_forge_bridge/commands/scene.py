# SPDX-License-Identifier: GPL-3.0-or-later
"""SCENE.SNAPSHOT: what the 3D viewport shows, as JSON, without a screenshot.

Same schema as the Unreal command (WILDFRAME_SCENE_SNAPSHOT_V1), so an AI reads both apps the same way. Lengths are
in centimetres (Blender metres x 100); positions and rotations are in Blender's own axes (right-handed, Z up), which
the 'axes' field states.
"""

import math
import time

import bpy
from mathutils import Vector

from ..registry import CommandError, command

GEOMETRY = {"MESH", "CURVE", "SURFACE", "FONT", "META", "CURVES", "POINTCLOUD", "VOLUME", "GPENCIL", "GREASEPENCIL"}
EDGES = ((0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7))


def _largest_view3d():
    best = None
    wm = bpy.context.window_manager
    for window in (wm.windows if wm else []):
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None or region.width <= 0 or region.height <= 0:
                continue
            if best is None or region.width * region.height > best[2].width * best[2].height:
                best = (window, area, region)
    return best


def _r(v, scale=10.0):
    return round(v * scale) / scale


def _vec_cm(v):
    return [_r(c * 100.0) for c in v]


def _world_box(obj):
    """(min, max) world AABB from the evaluated bound box, or None."""
    try:
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    except Exception:  # noqa: BLE001
        return None
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return lo, hi


def _project_box(persp, lo, hi, width, height):
    """Screen box in pixels (x0, y0 top-left, x1, y1) clipped to the frame, or None. Clips box edges at the near plane."""
    clip = []
    for i in range(8):
        p = Vector(((hi.x if i & 1 else lo.x), (hi.y if i & 2 else lo.y), (hi.z if i & 4 else lo.z), 1.0))
        clip.append(persp @ p)
    near = 1e-4
    pts = []

    def add(c):
        pts.append(((0.5 + 0.5 * c.x / c.w) * width, (0.5 - 0.5 * c.y / c.w) * height))

    for c in clip:
        if c.w > near:
            add(c)
    for a, b in EDGES:
        ca, cb = clip[a], clip[b]
        if (ca.w > near) != (cb.w > near):
            t = (near - ca.w) / (cb.w - ca.w)
            add(ca + (cb - ca) * t)
    if not pts:
        return None
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    if x1 < 0 or y1 < 0 or x0 > width or y0 > height:
        return None
    x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(float(width), x1), min(float(height), y1)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return x0, y0, x1, y1


def _family(a, b):
    return a == b or a.parent == b or b.parent == a


def _kind(obj):
    if obj.type == "ARMATURE":
        return "armature"
    if obj.type == "MESH" and any(m.type == "ARMATURE" for m in obj.modifiers):
        return "skeletal_mesh"
    return {"MESH": "mesh", "LIGHT": "light", "CAMERA": "camera", "EMPTY": "empty"}.get(obj.type, obj.type.lower())


@command("SCENE.SNAPSHOT", "Read-only snapshot of what the largest 3D viewport shows, as JSON (same schema as "
         "Unreal's SCENE.SNAPSHOT): viewport camera (location, rotation, FOV, size), file, mode, selection, frame, and "
         "each visible object (nearest first) with type, transform, bounds, distance, 2D screen box, % of frame, "
         "occlusion by ray casts, materials and action. Optional coarse object-ID grid.",
         params={"max_actors": {"type": "integer", "default": 100},
                 "min_screen_percent": {"type": "number", "default": 0.0},
                 "occlusion": {"type": "boolean", "default": True},
                 "grid": {"type": "boolean", "default": False},
                 "grid_columns": {"type": "integer", "default": 64},
                 "grid_rows": {"type": "integer", "default": 36},
                 "include_offscreen": {"type": "boolean", "default": False},
                 "include_hidden": {"type": "boolean", "default": False}})
def snapshot(params):
    started = time.perf_counter()
    found = _largest_view3d()
    if found is None:
        raise CommandError("NO_VIEWPORT", "No 3D viewport is open (Blender running in background?).")
    window, area, region = found
    space = area.spaces.active
    rv3d = space.region_3d
    width, height = region.width, region.height
    persp = rv3d.perspective_matrix
    view_inv = rv3d.view_matrix.inverted()
    eye = view_inv.translation.copy()
    ortho = not rv3d.is_perspective
    win = rv3d.window_matrix
    fov = math.degrees(2.0 * math.atan(1.0 / win[0][0])) if not ortho and win[0][0] else 0.0
    right = (view_inv.to_3x3() @ Vector((1, 0, 0))).normalized()
    up = (view_inv.to_3x3() @ Vector((0, 1, 0))).normalized()
    forward = (view_inv.to_3x3() @ Vector((0, 0, -1))).normalized()
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    depsgraph = bpy.context.evaluated_depsgraph_get()
    frame_area = float(width * height)

    considered, in_view, items = 0, 0, []
    for obj in scene.objects:
        visible = obj.visible_get(view_layer=view_layer)
        if not visible and not params["include_hidden"]:
            continue
        if obj.type not in GEOMETRY and obj.type not in ("LIGHT", "CAMERA", "ARMATURE", "EMPTY"):
            continue
        ev = obj.evaluated_get(depsgraph)
        if obj.type in GEOMETRY or obj.type == "ARMATURE":
            box = _world_box(ev)
        else:
            p = obj.matrix_world.translation
            box = (p - Vector((0.25, 0.25, 0.25)), p + Vector((0.25, 0.25, 0.25)))
        if box is None:
            continue
        lo, hi = box
        considered += 1
        closest = Vector((min(max(eye.x, lo.x), hi.x), min(max(eye.y, lo.y), hi.y), min(max(eye.z, lo.z), hi.z)))
        distance = (closest - eye).length
        inside = distance == 0.0
        pix = (0.0, 0.0, float(width), float(height)) if inside else _project_box(persp, lo, hi, width, height)
        percent = 0.0
        if pix:
            percent = (pix[2] - pix[0]) * (pix[3] - pix[1]) / frame_area * 100.0
            if percent < params["min_screen_percent"]:
                continue
            in_view += 1
        elif not params["include_offscreen"]:
            continue
        items.append({"obj": obj, "lo": lo, "hi": hi, "distance": distance, "pix": pix, "percent": percent,
                      "inside": inside})
    items.sort(key=lambda it: (it["pix"] is None, it["distance"]))
    cap = max(1, int(params["max_actors"]))
    truncated = len(items) > cap
    items = items[:cap]

    actors, id_of = [], {}
    for index, it in enumerate(items, 1):
        obj = it["obj"]
        id_of[obj.name] = index
        lo, hi = it["lo"], it["hi"]
        center, extent = (lo + hi) / 2.0, (hi - lo) / 2.0
        rot = obj.matrix_world.to_euler()
        entry = {"id": index, "label": obj.name, "class": obj.type, "kind": _kind(obj), "path": obj.name_full,
                 "locationCm": _vec_cm(obj.matrix_world.translation),
                 "rotation": [_r(math.degrees(a), 100.0) for a in rot], "rotationOrder": "xyz",
                 "scale": [_r(s, 1000.0) for s in obj.matrix_world.to_scale()],
                 "boundsCenterCm": _vec_cm(center), "boundsExtentCm": _vec_cm(extent),
                 "distanceCm": _r(it["distance"] * 100.0), "inView": it["pix"] is not None,
                 "selected": obj.select_get(view_layer=view_layer)}
        if obj.users_collection:
            entry["folder"] = obj.users_collection[0].name
        if not obj.visible_get(view_layer=view_layer):
            entry["hiddenInEditor"] = True
        mats = []
        for slot in getattr(obj, "material_slots", []):
            if slot.material and slot.material.name not in mats and len(mats) < 12:
                mats.append(slot.material.name)
        entry["materials"] = mats
        anim = obj.animation_data
        if anim and anim.action:
            entry["animation"] = {"asset": anim.action.name, "frame": scene.frame_current,
                                  "timeSec": _r(scene.frame_current / (scene.render.fps / scene.render.fps_base), 1000.0)}
        if it["pix"] is not None:
            x0, y0, x1, y1 = it["pix"]
            entry["screenBox"] = {"x0": _r(x0 / width, 10000.0), "y0": _r(y0 / height, 10000.0),
                                  "x1": _r(x1 / width, 10000.0), "y1": _r(y1 / height, 10000.0)}
            entry["screenPercent"] = _r(it["percent"], 100.0)
            if it["inside"]:
                entry["cameraInside"] = True
            if params["occlusion"]:
                entry["occlusion"] = _occlusion(scene, depsgraph, eye, obj, center, extent, right, up, it["inside"],
                                                ortho, forward)
        actors.append(entry)

    out = {"schema": "WILDFRAME_SCENE_SNAPSHOT_V1", "app": "blender", "axes": "blender (right-handed, Z up)",
           "units": "centimeters", "timestampUnix": int(time.time()),
           "level": {"map": bpy.data.filepath or "(unsaved)", "world": scene.name},
           "camera": {"locationCm": _vec_cm(eye),
                      "rotation": [_r(math.degrees(a), 100.0) for a in view_inv.to_euler()], "rotationOrder": "xyz",
                      "fovDegrees": _r(fov, 100.0), "width": width, "height": height,
                      "view": rv3d.view_perspective, "orthographic": ortho},
           "editor": {"modes": [bpy.context.mode], "openAssetEditors": sorted({a.type for a in window.screen.areas}),
                      "selection": [o.name for o in bpy.context.selected_objects],
                      "activeObject": view_layer.objects.active.name if view_layer.objects.active else None,
                      "shading": space.shading.type, "playInEditor": bool(bpy.context.screen.is_animation_playing),
                      "sequencer": {"frame": scene.frame_current, "start": scene.frame_start, "end": scene.frame_end,
                                    "fps": round(scene.render.fps / scene.render.fps_base, 3)}},
           "counts": {"consideredActors": considered, "inView": in_view, "returned": len(actors),
                      "truncated": truncated},
           "actors": actors}
    if params["grid"]:
        out["idGrid"] = _grid(scene, depsgraph, region, rv3d, id_of, int(params["grid_columns"]),
                              int(params["grid_rows"]), actors)
    out["timeMs"] = _r((time.perf_counter() - started) * 1000.0, 100.0)
    out["_message"] = "%d of %d objects in view (%d returned) in %.1f ms." % (in_view, considered, len(actors),
                                                                              out["timeMs"])
    return out


def _occlusion(scene, depsgraph, eye, obj, center, extent, right, up, inside, ortho, forward):
    if inside:
        return {"state": "visible", "visibleSamples": 1, "samples": 1}
    points = [center]
    if obj.type not in ("LIGHT", "CAMERA", "EMPTY"):
        half_r = abs(right.x) * extent.x + abs(right.y) * extent.y + abs(right.z) * extent.z
        half_u = abs(up.x) * extent.x + abs(up.y) * extent.y + abs(up.z) * extent.z
        points += [center + right * half_r * 0.5, center - right * half_r * 0.5,
                   center + up * half_u * 0.5, center - up * half_u * 0.5]
    visible, blockers = 0, {}
    for p in points:
        origin = (p - forward * 10000.0) if ortho else eye
        to = p - origin
        dist = to.length
        if dist < 1e-6:
            visible += 1
            continue
        hit, _loc, _n, _i, hit_obj, _m = scene.ray_cast(depsgraph, origin, to / dist, distance=dist)
        if hit and hit_obj is not None:
            original = hit_obj.original if hasattr(hit_obj, "original") else hit_obj
            if not _family(original, obj) and (_loc - origin).length < dist - 0.05:
                blockers[original.name] = blockers.get(original.name, 0) + 1
                continue
        visible += 1
    state = "visible" if visible == len(points) else ("hidden" if visible == 0 else "partial")
    out = {"state": state, "visibleSamples": visible, "samples": len(points)}
    if blockers:
        out["blockedBy"] = max(blockers, key=blockers.get)
    return out


def _grid(scene, depsgraph, region, rv3d, id_of, cols, rows, actors):
    from bpy_extras import view3d_utils
    cols, rows = max(1, min(cols, 256)), max(1, min(rows, 256))
    by_id = {a["label"]: a for a in actors}
    cells = []
    for r in range(rows):
        row = []
        for c in range(cols):
            px = ((c + 0.5) * region.width / cols, region.height - (r + 0.5) * region.height / rows)
            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, px)
            direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, px)
            hit, _l, _n, _i, obj, _m = scene.ray_cast(depsgraph, origin, direction, distance=1.0e5)
            cell = -1
            if hit and obj is not None:
                original = obj.original if hasattr(obj, "original") else obj
                cell = -2
                o = original
                while o is not None:
                    if o.name in id_of:
                        cell = id_of[o.name]
                        break
                    o = o.parent
                if cell > 0:
                    by_id[o.name]["gridCells"] = by_id[o.name].get("gridCells", 0) + 1
            row.append(cell)
        cells.append(row)
    return {"columns": cols, "rows": rows, "cells": cells,
            "legend": "Row-major, top row first. Each cell is the id of the object seen through the cell centre; "
                      "-1 = nothing, -2 = an object not in 'actors'."}
