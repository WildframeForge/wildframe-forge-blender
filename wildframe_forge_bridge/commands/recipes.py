# SPDX-License-Identifier: GPL-3.0-or-later
"""Wildframe Forge recipes for Blender: ready-made one-call tasks with short answers.

Same rules as the Unreal recipes: built-ins only, compact results, dryRun where it changes things,
one Undo step per call (the server pushes it).
"""

import math
import os

import bpy
import bmesh
import mathutils

from .. import ctx
from ..registry import CommandError, command
from . import render as render_cmds

MAX_NAMES = 12
NAMES = {"type": "array", "items": {"type": "string"},
         "description": "Object names. Default: the selected meshes, or every mesh if nothing is selected."}


def _meshes(names):
    if names:
        objs = ctx.get_objects(names)
    else:
        objs = [o for o in bpy.context.selected_objects if o.type == "MESH"] or \
               [o for o in bpy.context.scene.objects if o.type == "MESH"]
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        raise CommandError("NO_MESHES", "No mesh objects to work on.")
    return meshes


def _short(names):
    names = list(names)
    return names[:MAX_NAMES] + (["... +%d more" % (len(names) - MAX_NAMES)] if len(names) > MAX_NAMES else [])


def _world_bounds(objs):
    bpy.context.view_layer.update()  # bound_box is stale right after mesh edits
    lo = mathutils.Vector((1e18, 1e18, 1e18))
    hi = mathutils.Vector((-1e18, -1e18, -1e18))
    for obj in objs:
        for corner in obj.bound_box:
            p = obj.matrix_world @ mathutils.Vector(corner)
            lo = mathutils.Vector(map(min, lo, p))
            hi = mathutils.Vector(map(max, hi, p))
    return lo, hi


# ------------------------------------------------------------------ RECIPE.SCENE_SUMMARY

@command("RECIPE.SCENE_SUMMARY", "One-call overview of the Blender scene: objects by type, total vertices and "
         "faces, materials, collections, cameras, lights, frame range, units, and objects with unapplied scale or "
         "missing images. Use this instead of listing objects.", params={})
def scene_summary(params):
    scene = bpy.context.scene
    by_type, verts, faces = {}, 0, 0
    unapplied, heavy = [], []
    for obj in scene.objects:
        by_type[obj.type] = by_type.get(obj.type, 0) + 1
        if obj.type == "MESH" and obj.data:
            v, f = len(obj.data.vertices), len(obj.data.polygons)
            verts += v
            faces += f
            if f > 200000:
                heavy.append("%s (%d faces)" % (obj.name, f))
            if any(abs(s - 1.0) > 1e-4 for s in obj.scale) or any(abs(r) > 1e-4 for r in obj.rotation_euler):
                unapplied.append(obj.name)
    missing = [img.name for img in bpy.data.images
               if img.source == "FILE" and img.filepath and not img.packed_file
               and not os.path.isfile(bpy.path.abspath(img.filepath))]
    return {
        "file": bpy.data.filepath or "(unsaved)",
        "objects": len(scene.objects), "byType": by_type, "vertices": verts, "faces": faces,
        "materials": len(bpy.data.materials), "collections": [c.name for c in bpy.data.collections][:20],
        "camera": scene.camera.name if scene.camera else None,
        "frames": [scene.frame_start, scene.frame_end, scene.render.fps],
        "units": {"system": scene.unit_settings.system, "scale": round(scene.unit_settings.scale_length, 4)},
        "unappliedTransforms": _short(unapplied), "heavyMeshes": _short(heavy), "missingImages": _short(missing),
        "_message": "%d objects, %s faces, %d materials." % (len(scene.objects), format(faces, ","), len(bpy.data.materials)),
    }


# ------------------------------------------------------------------ RECIPE.CLEAN_MESH

@command("RECIPE.CLEAN_MESH", "Clean messy meshes (Tripo/AI/scan models) in one call: merge duplicate vertices, "
         "remove loose geometry, fix normals, optional limited dissolve, triangulate and decimate to a face budget. "
         "Reports faces before/after.",
         params={"names": NAMES, "merge_distance": {"type": "number", "default": 0.0001},
                 "remove_loose": {"type": "boolean", "default": True},
                 "fix_normals": {"type": "boolean", "default": True},
                 "dissolve_angle": {"type": "number", "description": "Limited dissolve angle in degrees (e.g. 1)."},
                 "max_faces": {"type": "integer", "description": "Decimate each mesh down to about this many faces."},
                 "triangulate": {"type": "boolean", "default": False},
                 "dryRun": {"type": "boolean", "default": False}}, mutating=True)
def clean_mesh(params):
    objs = _meshes(params.get("names"))
    if params.get("dryRun"):
        faces = sum(len(o.data.polygons) for o in objs)
        return {"dryRun": True, "objects": _short(o.name for o in objs), "faces": faces,
                "_message": "Dry run: would clean %d mesh(es) with %s faces." % (len(objs), format(faces, ","))}
    report, before_total, after_total, shared = [], 0, 0, []
    done = set()
    with ctx.object_mode():
        for obj in objs:
            mesh = obj.data
            if mesh.name in done:
                continue
            done.add(mesh.name)
            if mesh.users > 1:
                shared.append(obj.name)
            before = len(mesh.polygons)
            bm = bmesh.new()
            bm.from_mesh(mesh)
            merged = len(bm.verts)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=float(params.get("merge_distance") or 0.0001))
            merged -= len(bm.verts)
            loose = 0
            if params.get("remove_loose", True):
                loose_verts = [v for v in bm.verts if not v.link_edges]
                loose_edges = [e for e in bm.edges if not e.link_faces]
                loose = len(loose_verts) + len(loose_edges)
                bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
                bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_edges], context="VERTS")
            if params.get("dissolve_angle"):
                bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(float(params["dissolve_angle"])),
                                         verts=bm.verts, edges=bm.edges)
            if params.get("fix_normals", True) and bm.faces:
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            if params.get("triangulate"):
                bmesh.ops.triangulate(bm, faces=bm.faces)
            bm.to_mesh(mesh)
            bm.free()
            mesh.update()
            if params.get("max_faces") and len(mesh.polygons) > int(params["max_faces"]):
                ratio = max(0.01, min(1.0, int(params["max_faces"]) / float(len(mesh.polygons))))
                mod = obj.modifiers.new("Wildframe_Decimate", "DECIMATE")
                mod.ratio = ratio
                ctx.select_only([obj])
                with ctx.view3d():
                    bpy.ops.object.modifier_apply(modifier=mod.name)
            after = len(obj.data.polygons)
            before_total += before
            after_total += after
            report.append({"object": obj.name, "facesBefore": before, "facesAfter": after,
                           "mergedVerts": merged, "looseRemoved": loose})
    warnings = ["Shared mesh data (also changed on its other users): %s" % ", ".join(_short(shared))] if shared else []
    return {"objects": report[:MAX_NAMES], "facesBefore": before_total, "facesAfter": after_total,
            "_message": "Cleaned %d mesh(es): %s -> %s faces." % (len(report), format(before_total, ","), format(after_total, ",")),
            "_warnings": warnings}


# ------------------------------------------------------------------ RECIPE.PREP_FOR_UNREAL

@command("RECIPE.PREP_FOR_UNREAL", "Get meshes ready for Unreal in one call: apply rotation and scale, put the "
         "origin at the bottom centre (so they sit on the ground), optionally scale to a real height in metres, "
         "move to the world origin and add an SM_ name prefix. Then send with BRIDGE.SEND_TO_UNREAL.",
         params={"names": NAMES, "origin": {"type": "string", "enum": ["BOTTOM_CENTER", "CENTER", "KEEP"],
                                             "default": "BOTTOM_CENTER"},
                 "height_m": {"type": "number", "description": "Scale uniformly so the object is this tall."},
                 "to_world_origin": {"type": "boolean", "default": False},
                 "prefix": {"type": "string", "default": "", "description": "e.g. SM_ (skipped if already there)."},
                 "dryRun": {"type": "boolean", "default": False}}, mutating=True)
def prep_for_unreal(params):
    objs = _meshes(params.get("names"))
    if params.get("dryRun"):
        return {"dryRun": True, "objects": _short(o.name for o in objs),
                "_message": "Dry run: would prepare %d mesh(es) (origin %s)." % (len(objs), params.get("origin"))}
    report, shared = [], []
    with ctx.object_mode():
        for obj in objs:
            mesh = obj.data
            if mesh.users > 1:
                shared.append(obj.name)
                continue
            loc, rot, scale = obj.matrix_basis.decompose()
            mesh.transform(mathutils.Matrix.LocRotScale(None, rot, scale))
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = (0.0, 0.0, 0.0)
            obj.scale = (1.0, 1.0, 1.0)
            if params.get("height_m") and mesh.vertices:
                zs = [v.co.z for v in mesh.vertices]
                height = max(zs) - min(zs)
                if height > 1e-6:
                    factor = float(params["height_m"]) / height
                    mesh.transform(mathutils.Matrix.Scale(factor, 4))
            origin = params.get("origin") or "BOTTOM_CENTER"
            if origin != "KEEP" and mesh.vertices:
                xs = [v.co.x for v in mesh.vertices]
                ys = [v.co.y for v in mesh.vertices]
                zs = [v.co.z for v in mesh.vertices]
                pivot = mathutils.Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                                          min(zs) if origin == "BOTTOM_CENTER" else (min(zs) + max(zs)) / 2))
                mesh.transform(mathutils.Matrix.Translation(-pivot))
                obj.location = obj.location + pivot
            if params.get("to_world_origin"):
                obj.location = (0.0, 0.0, 0.0)
            mesh.update()
            prefix = params.get("prefix") or ""
            if prefix and not obj.name.startswith(prefix):
                obj.name = prefix + obj.name
            bpy.context.view_layer.update()
            dims = obj.dimensions
            report.append({"object": obj.name, "sizeM": [round(dims.x, 3), round(dims.y, 3), round(dims.z, 3)]})
    warnings = ["Skipped (mesh shared by several objects): %s" % ", ".join(_short(shared))] if shared else []
    return {"objects": report[:MAX_NAMES],
            "_message": "Prepared %d mesh(es) for Unreal." % len(report), "_warnings": warnings}


# ------------------------------------------------------------------ RECIPE.STUDIO_LIGHTS

STUDIO = {
    # name: [(label, yaw deg, pitch deg, power W, size m, colour)], world strength
    "three_point": ([("Key", 45, 35, 1000, 2.0, (1.0, 0.96, 0.9)), ("Fill", -60, 15, 350, 3.0, (0.9, 0.95, 1.0)),
                     ("Rim", 180, 40, 800, 1.5, (1.0, 1.0, 1.0))], 0.3),
    "soft": ([("Key", 30, 45, 700, 5.0, (1.0, 0.98, 0.95)), ("Fill", -90, 20, 400, 5.0, (0.95, 0.97, 1.0))], 0.6),
    "dramatic": ([("Key", 70, 20, 1500, 1.0, (1.0, 0.85, 0.7)), ("Rim", -150, 35, 1200, 1.0, (0.7, 0.8, 1.0))], 0.05),
}


@command("RECIPE.STUDIO_LIGHTS", "Light objects for look-dev or turntables in one call: three_point, soft or "
         "dramatic area lights aimed at the objects (sized to them) plus a matching world strength. Replaces a "
         "previous Wildframe Forge studio rig.",
         params={"preset": {"type": "string", "enum": list(STUDIO), "default": "three_point"}, "names": NAMES},
         mutating=True)
def studio_lights(params):
    preset = params.get("preset") or "three_point"
    lights, world_strength = STUDIO[preset]
    objs = _meshes(params.get("names"))
    lo, hi = _world_bounds(objs)
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.1)
    coll = bpy.data.collections.get("Wildframe Forge Studio")
    if coll is None:
        coll = bpy.data.collections.new("Wildframe Forge Studio")
        bpy.context.scene.collection.children.link(coll)
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    made = []
    for label, yaw, pitch, power, size, color in lights:
        data = bpy.data.lights.new("Wildframe Forge " + label, "AREA")
        data.energy = power * (radius / 1.0) ** 2
        data.size = size * radius
        data.color = color
        obj = bpy.data.objects.new("Wildframe Forge " + label, data)
        coll.objects.link(obj)
        dist = radius * 3.0
        y, p = math.radians(yaw), math.radians(pitch)
        obj.location = center + mathutils.Vector((math.cos(y) * math.cos(p), math.sin(y) * math.cos(p), math.sin(p))) * dist
        obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()
        made.append(obj.name)
    world = bpy.context.scene.world
    if world and world.use_nodes:
        bg = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
        if bg:
            bg.inputs[1].default_value = world_strength
    return {"preset": preset, "lights": made, "center": ctx.to_list(center, 3),
            "_message": "Added %s studio lights (%d) around %d object(s)." % (preset.replace("_", " "), len(made), len(objs))}


# ------------------------------------------------------------------ RECIPE.PREVIEW_RENDER

@command("RECIPE.PREVIEW_RENDER", "Quick preview image of objects in one call: a temporary camera frames them from "
         "the given angle, renders with Eevee at low samples, then is removed. Returns the PNG path (read it with "
         "read_image). Nothing else in the scene changes.",
         params={"names": NAMES, "yaw": {"type": "number", "default": 35}, "pitch": {"type": "number", "default": 20},
                 "resolution": {"type": "array", "default": [1280, 720]}, "samples": {"type": "integer", "default": 16},
                 "path": {"type": "string"}}, long_running=True)
def preview_render(params):
    scene = bpy.context.scene
    objs = _meshes(params.get("names"))
    lo, hi = _world_bounds(objs)
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.05)
    cam_data = bpy.data.cameras.new("Wildframe Forge Preview")
    cam_data.lens = 50
    cam = bpy.data.objects.new("Wildframe Forge Preview", cam_data)
    scene.collection.objects.link(cam)
    res = params.get("resolution") or [1280, 720]
    aspect = max(int(res[0]), 1) / max(int(res[1]), 1)
    fov = 2 * math.atan(cam_data.sensor_width / (2 * cam_data.lens))  # horizontal (sensor fit AUTO)
    if aspect >= 1.0:
        fov = 2 * math.atan(math.tan(fov / 2) / aspect)  # the narrower vertical angle limits the framing
    dist = radius / math.sin(fov / 2) * 1.15
    y, p = math.radians(float(params.get("yaw", 35))), math.radians(float(params.get("pitch", 20)))
    cam.location = center + mathutils.Vector((math.cos(y) * math.cos(p), -math.sin(y) * math.cos(p), math.sin(p))) * dist
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.clip_end = max(1000.0, dist * 4)
    # default name is unique per call: another AI client may preview the same object at the same time
    path = os.path.abspath(params.get("path") or render_cmds._default_png(
        "preview_%s" % "".join(c if c.isalnum() or c in "-_" else "_" for c in objs[0].name)[:40]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    saved = {"camera": scene.camera, "x": scene.render.resolution_x, "y": scene.render.resolution_y,
             "pct": scene.render.resolution_percentage, "engine": scene.render.engine,
             "fmt": scene.render.image_settings.file_format, "out": scene.render.filepath}
    try:
        scene.camera = cam
        scene.render.resolution_x, scene.render.resolution_y = int(res[0]), int(res[1])
        scene.render.resolution_percentage = 100
        for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = engine
                break
            except TypeError:
                continue
        if hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = int(params.get("samples") or 16)
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
    finally:
        scene.camera = saved["camera"]
        scene.render.resolution_x, scene.render.resolution_y = saved["x"], saved["y"]
        scene.render.resolution_percentage = saved["pct"]
        scene.render.engine = saved["engine"]
        scene.render.image_settings.file_format = saved["fmt"]
        scene.render.filepath = saved["out"]
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_data)
    return {"path": path, "exists": os.path.isfile(path), "framed": _short(o.name for o in objs),
            "_message": "Preview saved to %s." % path}
