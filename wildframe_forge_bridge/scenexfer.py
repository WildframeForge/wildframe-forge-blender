# SPDX-License-Identifier: GPL-3.0-or-later
"""Lights and cameras between Blender and Unreal (no files: plain values in the exchange package).

Item formats (kind "light" / "camera"):
    {"kind": "light", "name": ..., "light": {"type": "POINT|SUN|SPOT|AREA", "color": [r,g,b], "watts": float,
     "radius": m, "spotAngle": deg (full cone), "spotBlend": 0..1, "width": m, "height": m, "shadows": bool},
     "blenderMatrix": 4x4 | "unrealLocationCm"+"unrealAxes"}
    {"kind": "camera", "name": ..., "camera": {"focalLength": mm, "sensorWidth": mm, "sensorHeight": mm,
     "fStop": f, "focusDistance": m (0 = off), "clipStart": m, "clipEnd": m, "ortho": bool, "orthoWidth": m}, ...}

Orientation: Blender lights/cameras look down their local -Z with +Y up; Unreal ones look along +X with +Z up. The
Unreal side converts with forward = -Z column, up = +Y column (handedness flip y -> -y).
Brightness: Blender's watts use its own 683 lm/W convention: sun W/m^2 * 683 = lux; point/spot W * 683 / (4 pi) =
candela; area W * 683 / pi = nits*m^2 (rect). Unreal converts back the same way, so a round trip is exact.
"""

import math

import bpy

LUMENS_PER_WATT = 683.0


def describe_light(obj):
    data = obj.data
    out = {"type": data.type, "color": [round(c, 5) for c in data.color], "watts": float(data.energy),
           "shadows": bool(getattr(data, "use_shadow", True))}
    if data.type in ("POINT", "SPOT"):
        out["radius"] = float(getattr(data, "shadow_soft_size", 0.0))
    if data.type == "SPOT":
        out["spotAngle"] = math.degrees(data.spot_size)
        out["spotBlend"] = float(data.spot_blend)
    if data.type == "AREA":
        out["shape"] = data.shape
        out["width"] = float(data.size)
        out["height"] = float(data.size_y if data.shape in ("RECTANGLE", "ELLIPSE") else data.size)
    if data.type == "SUN":
        out["angle"] = math.degrees(getattr(data, "angle", 0.0))
    return out


def describe_camera(obj):
    cam = obj.data
    out = {"focalLength": float(cam.lens), "sensorWidth": float(cam.sensor_width),
           "sensorHeight": float(cam.sensor_height), "clipStart": float(cam.clip_start), "clipEnd": float(cam.clip_end),
           "ortho": cam.type == "ORTHO", "orthoWidth": float(cam.ortho_scale)}
    if cam.dof.use_dof:
        dist = cam.dof.focus_distance
        if cam.dof.focus_object is not None:
            dist = (cam.dof.focus_object.matrix_world.translation - obj.matrix_world.translation).length
        out["focusDistance"] = float(dist)
        out["fStop"] = float(cam.dof.aperture_fstop)
    return out


def describe(obj):
    if obj.type == "LIGHT":
        return {"kind": "light", "light": describe_light(obj)}
    if obj.type == "CAMERA":
        return {"kind": "camera", "camera": describe_camera(obj)}
    return None


def _unreal_matrix(item):
    """Blender world matrix for a light/camera placed in Unreal (axes: forward(+X), right(+Y), up(+Z))."""
    from mathutils import Matrix, Vector
    loc = item.get("unrealLocationCm") or [0, 0, 0]
    axes = item.get("unrealAxes")
    mat = Matrix.Identity(4)
    if axes:
        flip = lambda v: Vector((v[0], -v[1], v[2]))  # noqa: E731
        fwd, up = flip(axes[0]).normalized(), flip(axes[2]).normalized()
        z = -fwd                      # Blender camera/light looks down -Z
        y = up
        x = y.cross(z).normalized()
        for r in range(3):
            mat[r][0], mat[r][1], mat[r][2] = x[r], y[r], z[r]
    mat[0][3], mat[1][3], mat[2][3] = loc[0] / 100.0, -loc[1] / 100.0, loc[2] / 100.0
    return mat


def build(item, collection):
    """Create a Blender light/camera object from an item sent by Unreal."""
    name = item.get("name") or item["kind"].title()
    if item["kind"] == "light":
        L = item["light"]
        kind = L.get("type", "POINT")
        data = bpy.data.lights.new(name, kind)
        data.color = L.get("color", [1, 1, 1])[:3]
        data.energy = float(L.get("watts", 1000.0))
        if hasattr(data, "use_shadow"):
            data.use_shadow = bool(L.get("shadows", True))
        if kind in ("POINT", "SPOT") and "radius" in L:
            data.shadow_soft_size = float(L["radius"])
        if kind == "SPOT":
            data.spot_size = math.radians(float(L.get("spotAngle", 45.0)))
            data.spot_blend = float(L.get("spotBlend", 0.15))
        if kind == "AREA":
            data.shape = "RECTANGLE"
            data.size = float(L.get("width", 1.0))
            data.size_y = float(L.get("height", 1.0))
        if kind == "SUN" and "angle" in L:
            data.angle = math.radians(float(L["angle"]))
    else:
        C = item["camera"]
        data = bpy.data.cameras.new(name)
        data.lens = float(C.get("focalLength", 35.0))
        data.sensor_fit = "HORIZONTAL"
        data.sensor_width = float(C.get("sensorWidth", 36.0))
        data.sensor_height = float(C.get("sensorHeight", 24.0))
        data.clip_start = float(C.get("clipStart", 0.1))
        data.clip_end = float(C.get("clipEnd", 1000.0))
        if C.get("ortho"):
            data.type = "ORTHO"
            data.ortho_scale = float(C.get("orthoWidth", 10.0))
        if C.get("focusDistance"):
            data.dof.use_dof = True
            data.dof.focus_distance = float(C["focusDistance"])
            data.dof.aperture_fstop = float(C.get("fStop", 2.8))
    for old in list(collection.objects):  # re-sending replaces the light/camera from the previous send
        if old.get("wildframe_from_unreal") and old.name.split(".")[0] == name:
            bpy.data.objects.remove(old)
    obj = bpy.data.objects.new(name, data)
    obj["wildframe_from_unreal"] = True
    collection.objects.link(obj)
    obj.matrix_world = _unreal_matrix(item)
    return obj
