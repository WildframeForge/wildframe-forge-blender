# SPDX-License-Identifier: GPL-3.0-or-later
"""Objects, collections, lights, cameras, mesh data and modifiers."""

import math

import bpy
import bmesh
import mathutils

from .. import ctx
from ..registry import CommandError, command

VEC3 = {"type": "array", "description": "[x, y, z]"}


def _link(obj, collection=None):
    target = bpy.data.collections.get(collection) if collection else bpy.context.scene.collection
    if collection and target is None:
        target = bpy.data.collections.new(collection)
        bpy.context.scene.collection.children.link(target)
    target.objects.link(obj)
    return target


def _apply_transform(obj, params):
    if params.get("location") is not None:
        obj.location = ctx.vec(params["location"], name="location")
    if params.get("rotation") is not None:
        r = ctx.vec(params["rotation"], name="rotation")
        obj.rotation_euler = [math.radians(v) for v in r] if params.get("degrees", True) else r
    if params.get("scale") is not None:
        s = params["scale"]
        obj.scale = [float(s)] * 3 if isinstance(s, (int, float)) else ctx.vec(s, name="scale")


# ------------------------------------------------------------------ query

@command("OBJECTS.LIST", "List objects (name, type, transform). Filter by type, collection, name text or selection.",
         params={"type": {"type": "string", "description": "MESH, LIGHT, CAMERA, EMPTY, ARMATURE, CURVE ..."},
                 "collection": {"type": "string"}, "name_contains": {"type": "string"},
                 "selected_only": {"type": "boolean", "default": False},
                 "limit": {"type": "integer", "default": 500}})
def list_objects(params):
    objs = list(bpy.context.selected_objects if params["selected_only"] else bpy.context.scene.objects)
    if params.get("type"):
        objs = [o for o in objs if o.type == params["type"].upper()]
    if params.get("collection"):
        objs = [o for o in objs if params["collection"] in [c.name for c in o.users_collection]]
    if params.get("name_contains"):
        text = params["name_contains"].lower()
        objs = [o for o in objs if text in o.name.lower()]
    total = len(objs)
    return {"total": total, "objects": [ctx.object_summary(o) for o in objs[:max(1, params["limit"])]],
            "truncated": total > params["limit"]}


@command("OBJECTS.GET", "Everything about one object: transform, dimensions, mesh stats, materials, modifiers, "
         "children, custom properties, animation.", params={"name": {"type": "string"}}, required=["name"])
def get_object(params):
    return ctx.object_summary(ctx.get_object(params["name"]), detail=True)


# ------------------------------------------------------------------ create

PRIMITIVES = ["CUBE", "UV_SPHERE", "ICO_SPHERE", "CYLINDER", "CONE", "TORUS", "PLANE", "CIRCLE", "GRID", "MONKEY"]


@command("OBJECTS.CREATE_PRIMITIVE", "Add a mesh primitive with an optional name, size, transform and collection. "
         "Rotation is in degrees.",
         params={"primitive": {"type": "string", "enum": PRIMITIVES}, "name": {"type": "string"},
                 "size": {"type": "number", "default": 2.0}, "location": VEC3, "rotation": VEC3,
                 "scale": {"type": ["array", "number"]}, "collection": {"type": "string"},
                 "segments": {"type": "integer", "description": "sphere/cylinder/cone/circle resolution"}},
         required=["primitive"], mutating=True)
def create_primitive(params):
    kind = params["primitive"]
    size = float(params["size"])
    mesh = bpy.data.meshes.new(params.get("name") or kind.title())
    bm = bmesh.new()
    seg = params.get("segments") or 32
    if kind == "CUBE":
        bmesh.ops.create_cube(bm, size=size)
    elif kind == "UV_SPHERE":
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(3, seg // 2), radius=size / 2)
    elif kind == "ICO_SPHERE":
        bmesh.ops.create_icosphere(bm, subdivisions=3, radius=size / 2)
    elif kind == "CYLINDER":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=size / 2, radius2=size / 2, depth=size)
    elif kind == "CONE":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=size / 2, radius2=0.0, depth=size)
    elif kind == "PLANE":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2)
    elif kind == "GRID":
        bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=size / 2)
    elif kind == "CIRCLE":
        bmesh.ops.create_circle(bm, cap_ends=False, segments=seg, radius=size / 2)
    elif kind == "MONKEY":
        bmesh.ops.create_monkey(bm)
    elif kind == "TORUS":
        bm.free()
        with ctx.view3d():
            bpy.ops.mesh.primitive_torus_add(major_radius=size / 2, minor_radius=size / 8)
        obj = bpy.context.active_object
        if params.get("name"):
            obj.name = params["name"]
        _apply_transform(obj, params)
        bpy.data.meshes.remove(mesh)
        return ctx.object_summary(obj)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(params.get("name") or kind.title(), mesh)
    _link(obj, params.get("collection"))
    _apply_transform(obj, params)
    ctx.select_only([obj])
    return ctx.object_summary(obj)


@command("OBJECTS.CREATE_EMPTY", "Add an empty (null) object, e.g. as a parent or marker.",
         params={"name": {"type": "string", "default": "Empty"},
                 "display": {"type": "string", "default": "PLAIN_AXES",
                             "enum": ["PLAIN_AXES", "ARROWS", "SINGLE_ARROW", "CIRCLE", "CUBE", "SPHERE", "CONE"]},
                 "size": {"type": "number", "default": 1.0}, "location": VEC3, "rotation": VEC3,
                 "collection": {"type": "string"}}, mutating=True)
def create_empty(params):
    obj = bpy.data.objects.new(params["name"], None)
    obj.empty_display_type = params["display"]
    obj.empty_display_size = params["size"]
    _link(obj, params.get("collection"))
    _apply_transform(obj, params)
    return ctx.object_summary(obj)


@command("MESH.CREATE_FROM_DATA", "Create a mesh object from raw vertices [[x,y,z],...] and faces [[i,j,k,...],...] "
         "(optionally edges and per-face material index).",
         params={"name": {"type": "string"}, "vertices": {"type": "array"}, "faces": {"type": "array", "default": []},
                 "edges": {"type": "array", "default": []}, "location": VEC3, "collection": {"type": "string"},
                 "smooth": {"type": "boolean", "default": False}},
         required=["name", "vertices"], mutating=True)
def create_from_data(params):
    verts = [ctx.vec(v, name="vertices") for v in params["vertices"]]
    if len(verts) > 2_000_000:
        raise CommandError("TOO_MANY_VERTICES", "Limit is 2,000,000 vertices per call.")
    faces = [list(map(int, f)) for f in params["faces"]]
    n = len(verts)
    for face in faces:
        if any(i < 0 or i >= n for i in face):
            raise CommandError("BAD_FACE_INDEX", "Face %s references a missing vertex." % face)
    mesh = bpy.data.meshes.new(params["name"])
    mesh.from_pydata(verts, [list(map(int, e)) for e in params["edges"]], faces)
    mesh.validate(clean_customdata=False)
    mesh.update()
    if params["smooth"]:
        for poly in mesh.polygons:
            poly.use_smooth = True
    obj = bpy.data.objects.new(params["name"], mesh)
    _link(obj, params.get("collection"))
    _apply_transform(obj, params)
    return ctx.object_summary(obj, detail=True)


@command("LIGHTS.CREATE", "Add a light (POINT, SUN, SPOT, AREA) with energy (W), color, transform (degrees).",
         params={"type": {"type": "string", "enum": ["POINT", "SUN", "SPOT", "AREA"], "default": "POINT"},
                 "name": {"type": "string"}, "energy": {"type": "number", "default": 1000.0},
                 "color": {"type": "array", "default": [1.0, 1.0, 1.0]}, "location": VEC3, "rotation": VEC3,
                 "size": {"type": "number", "description": "Area size / spot cone angle (deg) / sun angle (deg)"},
                 "collection": {"type": "string"}}, mutating=True)
def create_light(params):
    data = bpy.data.lights.new(params.get("name") or params["type"].title() + "Light", type=params["type"])
    data.energy = params["energy"]
    data.color = ctx.vec(params["color"], name="color")
    if params.get("size") is not None:
        if params["type"] == "AREA":
            data.size = params["size"]
        elif params["type"] == "SPOT":
            data.spot_size = math.radians(params["size"])
        elif params["type"] == "SUN":
            data.angle = math.radians(params["size"])
        else:
            data.shadow_soft_size = params["size"]
    obj = bpy.data.objects.new(data.name, data)
    _link(obj, params.get("collection"))
    _apply_transform(obj, params)
    return ctx.object_summary(obj, detail=True)


@command("CAMERAS.CREATE", "Add a camera (focal length mm, sensor, transform in degrees); optionally make it active "
         "and aim it at an object.",
         params={"name": {"type": "string", "default": "Camera"}, "focal_length": {"type": "number", "default": 50.0},
                 "sensor_width": {"type": "number", "default": 36.0}, "location": VEC3, "rotation": VEC3,
                 "look_at": {"type": "string", "description": "Object name to aim at"},
                 "make_active": {"type": "boolean", "default": True}, "collection": {"type": "string"}},
         mutating=True)
def create_camera(params):
    data = bpy.data.cameras.new(params["name"])
    data.lens = params["focal_length"]
    data.sensor_width = params["sensor_width"]
    obj = bpy.data.objects.new(params["name"], data)
    _link(obj, params.get("collection"))
    _apply_transform(obj, params)
    if params.get("look_at"):
        target = ctx.get_object(params["look_at"])
        direction = target.matrix_world.translation - obj.location
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    if params["make_active"]:
        bpy.context.scene.camera = obj
    return ctx.object_summary(obj, detail=True)


@command("CAMERAS.SET_ACTIVE", "Make an existing camera object the scene camera.",
         params={"name": {"type": "string"}}, required=["name"], mutating=True)
def set_active_camera(params):
    obj = ctx.get_object(params["name"])
    if obj.type != "CAMERA":
        raise CommandError("NOT_A_CAMERA", "%s is a %s." % (obj.name, obj.type))
    bpy.context.scene.camera = obj
    return {"camera": obj.name}


# ------------------------------------------------------------------ edit

@command("OBJECTS.SET_TRANSFORM", "Set location / rotation (degrees unless degrees=false) / scale of one or more "
         "objects. relative=true adds to the current values.",
         params={"names": {"type": "array"}, "location": VEC3, "rotation": VEC3, "scale": {"type": ["array", "number"]},
                 "degrees": {"type": "boolean", "default": True}, "relative": {"type": "boolean", "default": False}},
         required=["names"], mutating=True)
def set_transform(params):
    out = []
    for obj in ctx.get_objects(params["names"]):
        if params["relative"]:
            if params.get("location") is not None:
                obj.location = obj.location + mathutils.Vector(ctx.vec(params["location"]))
            if params.get("rotation") is not None:
                r = ctx.vec(params["rotation"])
                r = [math.radians(v) for v in r] if params["degrees"] else r
                obj.rotation_euler = [a + b for a, b in zip(obj.rotation_euler, r)]
            if params.get("scale") is not None:
                s = params["scale"]
                s = [float(s)] * 3 if isinstance(s, (int, float)) else ctx.vec(s)
                obj.scale = [a * b for a, b in zip(obj.scale, s)]
        else:
            _apply_transform(obj, params)
        out.append(ctx.object_summary(obj))
    return {"objects": out}


@command("OBJECTS.SET_PROPERTY", "Set any property by path on an object or its data, e.g. "
         "path='data.energy' value=500, path='hide_render' value=true, path='modifiers[\"Bevel\"].width' value=0.02. "
         "Use custom=true to set a custom property instead.",
         params={"name": {"type": "string"}, "path": {"type": "string"}, "value": {},
                 "custom": {"type": "boolean", "default": False}},
         required=["name", "path", "value"], mutating=True)
def set_property(params):
    obj = ctx.get_object(params["name"])
    if params["custom"]:
        obj[params["path"]] = params["value"]
        return {"name": obj.name, "path": params["path"], "value": ctx.jsonable(obj[params["path"]])}
    try:
        value = ctx.set_path(obj, params["path"].replace('"', "'").replace("['", "[").replace("']", "]"), params["value"])
    except (AttributeError, TypeError, ValueError, KeyError, IndexError) as error:
        raise CommandError("SET_PROPERTY_FAILED", str(error))
    return {"name": obj.name, "path": params["path"], "value": value}


@command("OBJECTS.RENAME", "Rename an object (and optionally its data block).",
         params={"name": {"type": "string"}, "new_name": {"type": "string"},
                 "rename_data": {"type": "boolean", "default": True}}, required=["name", "new_name"], mutating=True)
def rename(params):
    obj = ctx.get_object(params["name"])
    obj.name = params["new_name"]
    if params["rename_data"] and obj.data is not None and obj.data.users == 1:
        obj.data.name = params["new_name"]
    return {"name": obj.name}


@command("OBJECTS.DELETE", "Delete objects (and their now-unused mesh data). Needs confirm=true.",
         params={"names": {"type": "array"}, "confirm": {"type": "boolean", "default": False}},
         required=["names"], mutating=True, destructive=True)
def delete(params):
    if not params["confirm"]:
        raise CommandError("CONFIRM_REQUIRED", "Deleting objects needs confirm=true.")
    removed = []
    for obj in ctx.get_objects(params["names"]):
        data = obj.data
        removed.append(obj.name)
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and getattr(data, "users", 1) == 0:
            for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.lights, bpy.data.cameras):
                if data.name in coll and coll[data.name] == data:
                    coll.remove(data)
                    break
    return {"deleted": removed}


@command("OBJECTS.DUPLICATE", "Duplicate objects (linked=true shares mesh data). Optional offset.",
         params={"names": {"type": "array"}, "linked": {"type": "boolean", "default": False},
                 "offset": VEC3, "count": {"type": "integer", "default": 1}}, required=["names"], mutating=True)
def duplicate(params):
    created = []
    offset = mathutils.Vector(ctx.vec(params["offset"]) if params.get("offset") else (0, 0, 0))
    for obj in ctx.get_objects(params["names"]):
        for i in range(max(1, min(params["count"], 1000))):
            copy = obj.copy()
            if obj.data is not None and not params["linked"]:
                copy.data = obj.data.copy()
            for coll in obj.users_collection:
                coll.objects.link(copy)
            copy.location = obj.location + offset * (i + 1)
            created.append(copy.name)
    return {"created": created}


@command("OBJECTS.SELECT", "Select objects (replace or add) and set the active one. Empty names clears selection.",
         params={"names": {"type": "array", "default": []}, "add": {"type": "boolean", "default": False},
                 "active": {"type": "string"}})
def select(params):
    objs = ctx.get_objects(params["names"])
    if not params["add"]:
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
    for obj in objs:
        obj.select_set(True)
    if params.get("active"):
        bpy.context.view_layer.objects.active = ctx.get_object(params["active"])
    elif objs:
        bpy.context.view_layer.objects.active = objs[0]
    return {"selected": [o.name for o in bpy.context.selected_objects]}


@command("OBJECTS.PARENT", "Parent objects to a parent object (keep_transform keeps world position). parent=null "
         "clears the parent.",
         params={"names": {"type": "array"}, "parent": {"type": ["string", "null"]},
                 "keep_transform": {"type": "boolean", "default": True}}, required=["names"], mutating=True)
def parent(params):
    target = ctx.get_object(params["parent"]) if params.get("parent") else None
    for obj in ctx.get_objects(params["names"]):
        world = obj.matrix_world.copy()
        obj.parent = target
        if target is not None:
            obj.matrix_parent_inverse = target.matrix_world.inverted() if params["keep_transform"] else mathutils.Matrix()
        elif params["keep_transform"]:
            obj.matrix_world = world
    return {"parent": target.name if target else None, "children": params["names"]}


@command("OBJECTS.JOIN", "Join mesh objects into the first one (like Ctrl+J).",
         params={"names": {"type": "array"}}, required=["names"], mutating=True, destructive=True)
def join(params):
    objs = ctx.get_objects(params["names"])
    if any(o.type != "MESH" for o in objs):
        raise CommandError("NOT_MESH", "Only mesh objects can be joined.")
    with ctx.object_mode(), ctx.view3d():
        ctx.select_only(objs, objs[0])
        bpy.ops.object.join()
    return ctx.object_summary(bpy.context.view_layer.objects.active, detail=True)


@command("OBJECTS.APPLY_TRANSFORM", "Apply location/rotation/scale to the mesh data (Ctrl+A).",
         params={"names": {"type": "array"}, "location": {"type": "boolean", "default": False},
                 "rotation": {"type": "boolean", "default": True}, "scale": {"type": "boolean", "default": True}},
         required=["names"], mutating=True)
def apply_transform(params):
    objs = ctx.get_objects(params["names"])
    with ctx.object_mode(), ctx.view3d():
        ctx.select_only(objs)
        bpy.ops.object.transform_apply(location=params["location"], rotation=params["rotation"], scale=params["scale"])
    return {"objects": [ctx.object_summary(o) for o in objs]}


@command("OBJECTS.SET_ORIGIN", "Move object origins: GEOMETRY (to bounds center), CURSOR, or BOTTOM_CENTER "
         "(good for Unreal pivots).",
         params={"names": {"type": "array"}, "mode": {"type": "string", "default": "GEOMETRY",
                                                       "enum": ["GEOMETRY", "CURSOR", "BOTTOM_CENTER"]}},
         required=["names"], mutating=True)
def set_origin(params):
    objs = ctx.get_objects(params["names"])
    for obj in objs:
        if params["mode"] == "BOTTOM_CENTER" and obj.type == "MESH":
            corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
            center = sum(corners, mathutils.Vector()) / 8.0
            pivot = mathutils.Vector((center.x, center.y, min(c.z for c in corners)))
            local = obj.matrix_world.inverted() @ pivot
            obj.data.transform(mathutils.Matrix.Translation(-local))
            obj.matrix_world.translation = pivot
            continue
        with ctx.object_mode(), ctx.view3d():
            ctx.select_only([obj])
            bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY" if params["mode"] == "GEOMETRY" else "ORIGIN_CURSOR")
    return {"objects": [ctx.object_summary(o) for o in objs]}


@command("OBJECTS.SET_VISIBILITY", "Hide/show objects in the viewport and/or render.",
         params={"names": {"type": "array"}, "viewport": {"type": "boolean"}, "render": {"type": "boolean"}},
         required=["names"], mutating=True)
def set_visibility(params):
    for obj in ctx.get_objects(params["names"]):
        if "viewport" in params:
            obj.hide_set(not params["viewport"])
        if "render" in params:
            obj.hide_render = not params["render"]
    return {"names": params["names"]}


# ------------------------------------------------------------------ collections

@command("COLLECTIONS.LIST", "List collections with their objects and children.")
def list_collections(params):
    def walk(coll, depth=0):
        return {"name": coll.name, "objects": [o.name for o in coll.objects][:500],
                "children": [walk(c, depth + 1) for c in coll.children] if depth < 8 else []}
    return {"root": walk(bpy.context.scene.collection)}


@command("COLLECTIONS.MOVE_OBJECTS", "Move objects into a collection (created if missing); unlinks them from others.",
         params={"names": {"type": "array"}, "collection": {"type": "string"},
                 "parent": {"type": "string", "description": "Parent collection for a new collection"}},
         required=["names", "collection"], mutating=True)
def move_to_collection(params):
    target = bpy.data.collections.get(params["collection"])
    if target is None:
        target = bpy.data.collections.new(params["collection"])
        parent_coll = bpy.data.collections.get(params["parent"]) if params.get("parent") else bpy.context.scene.collection
        parent_coll.children.link(target)
    for obj in ctx.get_objects(params["names"]):
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        target.objects.link(obj)
    return {"collection": target.name, "objects": [o.name for o in target.objects][:500]}


# ------------------------------------------------------------------ modifiers & mesh

@command("MODIFIERS.ADD", "Add a modifier (BEVEL, SUBSURF, MIRROR, ARRAY, SOLIDIFY, DECIMATE, WEIGHTED_NORMAL, "
         "TRIANGULATE, BOOLEAN, REMESH, SMOOTH, DISPLACE ...) and set its settings, e.g. settings={'levels': 2}.",
         params={"name": {"type": "string"}, "type": {"type": "string"}, "modifier_name": {"type": "string"},
                 "settings": {"type": "object", "default": {}}}, required=["name", "type"], mutating=True)
def modifier_add(params):
    obj = ctx.get_object(params["name"])
    try:
        mod = obj.modifiers.new(params.get("modifier_name") or params["type"].title(), params["type"].upper())
    except TypeError as error:
        raise CommandError("BAD_MODIFIER_TYPE", str(error))
    applied, failed = {}, {}
    for key, value in params["settings"].items():
        try:
            if key == "object" and isinstance(value, str):
                value = ctx.get_object(value)
            setattr(mod, key, value)
            applied[key] = ctx.jsonable(getattr(mod, key))
        except Exception as error:  # noqa: BLE001
            failed[key] = str(error)
    out = {"object": obj.name, "modifier": mod.name, "type": mod.type, "applied": applied}
    if failed:
        out["_warnings"] = ["%s: %s" % kv for kv in failed.items()]
    return out


@command("MODIFIERS.APPLY", "Apply (bake) a modifier into the mesh.",
         params={"name": {"type": "string"}, "modifier": {"type": "string"}}, required=["name", "modifier"],
         mutating=True, destructive=True)
def modifier_apply(params):
    obj = ctx.get_object(params["name"])
    if params["modifier"] not in obj.modifiers:
        raise CommandError("MODIFIER_NOT_FOUND", "%s has no modifier %s." % (obj.name, params["modifier"]))
    with ctx.object_mode(), ctx.view3d():
        ctx.select_only([obj])
        with bpy.context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.modifier_apply(modifier=params["modifier"])
    return ctx.object_summary(obj, detail=True)


@command("MODIFIERS.REMOVE", "Remove a modifier.", params={"name": {"type": "string"}, "modifier": {"type": "string"}},
         required=["name", "modifier"], mutating=True)
def modifier_remove(params):
    obj = ctx.get_object(params["name"])
    mod = obj.modifiers.get(params["modifier"])
    if mod is None:
        raise CommandError("MODIFIER_NOT_FOUND", "%s has no modifier %s." % (obj.name, params["modifier"]))
    obj.modifiers.remove(mod)
    return {"object": obj.name, "modifiers": [m.name for m in obj.modifiers]}


@command("MESH.OPERATION", "Common mesh clean-up on whole objects: SHADE_SMOOTH, SHADE_FLAT, AUTO_SMOOTH, "
         "RECALC_NORMALS, MERGE_BY_DISTANCE, TRIANGULATE, UV_SMART_PROJECT, DECIMATE (ratio).",
         params={"names": {"type": "array"},
                 "operation": {"type": "string", "enum": ["SHADE_SMOOTH", "SHADE_FLAT", "AUTO_SMOOTH", "RECALC_NORMALS",
                                                          "MERGE_BY_DISTANCE", "TRIANGULATE", "UV_SMART_PROJECT", "DECIMATE"]},
                 "distance": {"type": "number", "default": 0.0001}, "ratio": {"type": "number", "default": 0.5},
                 "angle": {"type": "number", "default": 30.0}},
         required=["names", "operation"], mutating=True)
def mesh_operation(params):
    op = params["operation"]
    results = []
    for obj in ctx.get_objects(params["names"]):
        if obj.type != "MESH":
            continue
        me = obj.data
        if op in ("SHADE_SMOOTH", "SHADE_FLAT"):
            for poly in me.polygons:
                poly.use_smooth = op == "SHADE_SMOOTH"
        elif op == "AUTO_SMOOTH":
            with ctx.object_mode(), ctx.view3d():
                ctx.select_only([obj])
                try:
                    bpy.ops.object.shade_auto_smooth(angle=math.radians(params["angle"]))
                except (AttributeError, RuntimeError):
                    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(params["angle"]))
        elif op == "DECIMATE":
            mod = obj.modifiers.new("WildframeDecimate", "DECIMATE")
            mod.ratio = max(0.0, min(1.0, params["ratio"]))
            with ctx.object_mode(), ctx.view3d():
                ctx.select_only([obj])
                with bpy.context.temp_override(object=obj, active_object=obj):
                    bpy.ops.object.modifier_apply(modifier=mod.name)
        else:
            bm = bmesh.new()
            bm.from_mesh(me)
            if op == "RECALC_NORMALS":
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            elif op == "MERGE_BY_DISTANCE":
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=params["distance"])
            elif op == "TRIANGULATE":
                bmesh.ops.triangulate(bm, faces=bm.faces)
            if op == "UV_SMART_PROJECT":
                bm.free()
                with ctx.object_mode(), ctx.view3d():
                    ctx.select_only([obj])
                    bpy.ops.object.mode_set(mode="EDIT")
                    bpy.ops.mesh.select_all(action="SELECT")
                    bpy.ops.uv.smart_project()
                    bpy.ops.object.mode_set(mode="OBJECT")
            else:
                bm.to_mesh(me)
                bm.free()
        me.update()
        results.append({"name": obj.name, "vertices": len(me.vertices), "polygons": len(me.polygons)})
    return {"operation": op, "objects": results}
