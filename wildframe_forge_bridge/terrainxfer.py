# SPDX-License-Identifier: GPL-3.0-or-later
"""Terrain between Blender and Unreal Landscapes (heights only).

Blender -> Unreal: the evaluated terrain mesh is ray-cast from above on a grid Unreal accepts (vertex counts
k*63+1 per side), heights are stored as a 16-bit little-endian .r16 (32768 = the terrain's mid height, z scale picked
so the full height range uses ~98% of the 16 bits) and Unreal builds a real Landscape from it.

Unreal -> Blender: Unreal writes the landscape's exact 16-bit heights plus the grid transform; Blender rebuilds them
as a grid mesh (decimated when larger than 'max_size' vertices per side).

Axes: Unreal y = -Blender y, 1 m = 100 cm. Grid row 0 is Unreal's minimum y, i.e. Blender's maximum y.
"""

import math
import os

import bpy

QUADS_PER_COMPONENT = 63


def _world_mesh(obj):
    """(vertices Nx3 world metres, triangles Mx3) of the evaluated object."""
    import numpy as np
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    try:
        mesh.calc_loop_triangles()
        co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
        mesh.loop_triangles.foreach_get("vertices", tris)
        tris = tris.reshape(-1, 3)
    finally:
        ev.to_mesh_clear()
    m = np.array(obj.matrix_world, dtype=np.float64)
    world = co @ m[:3, :3].T + m[:3, 3]
    return world, tris


def _grid_quads(extent, spacing, forced=None):
    """Quads along one side: a multiple of 63 that keeps the mesh's own resolution."""
    if forced:
        return max(QUADS_PER_COMPONENT, int(round(forced / QUADS_PER_COMPONENT)) * QUADS_PER_COMPONENT)
    q = extent / spacing if spacing > 0 else QUADS_PER_COMPONENT
    comps = max(1, math.ceil(q / QUADS_PER_COMPONENT - 0.05))
    return min(comps, 64) * QUADS_PER_COMPONENT


def _fill_missing(h):
    """Fill NaN samples by growing the known heights outwards (average of known neighbours)."""
    import numpy as np
    h = h.copy()
    while np.isnan(h).any():
        known = ~np.isnan(h)
        val = np.where(known, h, 0.0)
        total = np.zeros_like(h)
        count = np.zeros_like(h)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            total += np.roll(np.roll(val, dy, 0), dx, 1) * _edge_mask(h.shape, dy, dx)
            count += np.roll(np.roll(known, dy, 0), dx, 1) * _edge_mask(h.shape, dy, dx)
        grow = (~known) & (count > 0)
        h[grow] = total[grow] / count[grow]
    return h


def _edge_mask(shape, dy, dx):
    """1 where the rolled neighbour is a real neighbour (no wrap-around)."""
    import numpy as np
    m = np.ones(shape)
    if dy > 0:
        m[:dy, :] = 0
    elif dy < 0:
        m[dy:, :] = 0
    if dx > 0:
        m[:, :dx] = 0
    elif dx < 0:
        m[:, dx:] = 0
    return m


def describe(obj, folder, name, resolution=0):
    """Write <name>.r16 for a terrain object and return its landscape item."""
    import numpy as np
    from mathutils.bvhtree import BVHTree
    verts, tris = _world_mesh(obj)
    if len(tris) == 0:
        raise ValueError("%s has no faces to sample" % obj.name)
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    width, depth = float(hi[0] - lo[0]), float(hi[1] - lo[1])
    if width <= 0 or depth <= 0:
        raise ValueError("%s is flat in X or Y; a landscape needs an area" % obj.name)
    stored = obj.get("wildframe_landscape_size")
    if stored and not resolution:  # came from Unreal: keep the exact grid
        quads_x, quads_y = int(stored[0]) - 1, int(stored[1]) - 1
        if quads_x % QUADS_PER_COMPONENT or quads_y % QUADS_PER_COMPONENT:
            stored = None
    if not stored or resolution:
        spacing = math.sqrt(width * depth / max(1, len(verts)))
        if resolution:
            longest = max(width, depth)
            quads_x = _grid_quads(width, longest / resolution)
            quads_y = _grid_quads(depth, longest / resolution)
        else:
            quads_x, quads_y = _grid_quads(width, spacing), _grid_quads(depth, spacing)
    size_x, size_y = quads_x + 1, quads_y + 1
    qx, qy = width / quads_x, depth / quads_y

    bvh = BVHTree.FromPolygons([tuple(v) for v in verts], [tuple(t) for t in tris], all_triangles=True)
    top = float(hi[2]) + 1.0
    ray = (0.0, 0.0, -1.0)
    from mathutils import Vector
    down = Vector(ray)
    eps = 1e-6 * max(width, depth)
    heights = np.full((size_y, size_x), np.nan, dtype=np.float64)
    xs = [float(lo[0]) + min(max(i * qx, eps), width - eps) for i in range(size_x)]
    for j in range(size_y):
        y = float(hi[1]) - min(max(j * qy, eps), depth - eps)
        row = heights[j]
        for i in range(size_x):
            hit = bvh.ray_cast(Vector((xs[i], y, top)), down)
            if hit[0] is not None:
                row[i] = hit[0][2]
    missing = int(np.isnan(heights).sum())
    if missing == heights.size:
        raise ValueError("no part of %s could be sampled from above" % obj.name)
    heights = _fill_missing(heights)
    zmin, zmax = float(heights.min()), float(heights.max())
    mid_cm = (zmin + zmax) * 50.0
    range_cm = (zmax - zmin) * 100.0
    scale_z = max(range_cm * 1.02 / 512.0, 0.01)
    h = np.clip(np.round(32768.0 + (heights * 100.0 - mid_cm) * 128.0 / scale_z), 0, 65535).astype("<u2")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name + ".r16")
    h.tofile(path)
    item = {"kind": "landscape", "name": name, "file": os.path.basename(path), "sizeX": size_x, "sizeY": size_y,
            "quadsPerSection": QUADS_PER_COMPONENT, "sectionsPerComponent": 1,
            "scaleCm": [qx * 100.0, qy * 100.0, scale_z],
            "centerCm": [(float(lo[0]) + width / 2) * 100.0, -(float(lo[1]) + depth / 2) * 100.0, mid_cm]}
    warnings = []
    if missing:
        warnings.append("%s: %d grid points had no surface above or below them (outside the "
                        "terrain or holes) and were filled from the nearest edge (a Landscape is a full rectangle)" % (name, missing))
    return item, warnings


def build(item, folder, collection, max_size=1025):
    """Grid mesh object from an Unreal landscape item."""
    import numpy as np
    sx, sy = int(item["sizeX"]), int(item["sizeY"])
    data = np.fromfile(os.path.join(folder, item["file"]), dtype="<u2")
    if data.size != sx * sy:
        raise ValueError("heightmap has %d values, expected %d" % (data.size, sx * sy))
    data = data.reshape(sy, sx).astype(np.float64)
    step = 1
    while (sx - 1) // step + 1 > max_size or (sy - 1) // step + 1 > max_size:
        step *= 2
    ii = np.arange(0, sx, step)
    jj = np.arange(0, sy, step)
    if ii[-1] != sx - 1:
        ii = np.append(ii, sx - 1)
    if jj[-1] != sy - 1:
        jj = np.append(jj, sy - 1)
    sub = data[np.ix_(jj, ii)]
    origin, ax, ay, az = (np.array(item[k], dtype=np.float64) for k in ("originCm", "axisXCm", "axisYCm", "axisZCm"))
    I, J = np.meshgrid(ii, jj)
    world = (origin[None, None, :] + I[..., None] * ax + J[..., None] * ay
             + ((sub - 32768.0) / 128.0)[..., None] * az)  # Unreal cm
    pts = world.reshape(-1, 3) * np.array([0.01, -0.01, 0.01])
    center = (pts.min(axis=0) + pts.max(axis=0)) / 2.0
    center[2] = 0.0
    pts -= center
    nx, ny = len(ii), len(jj)
    a = (np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)[None, :]).ravel()
    # Unreal's y flip mirrors the grid, so wind the quads the other way to keep normals up
    quads = np.stack([a, a + nx, a + nx + 1, a + 1], axis=1)
    name = item.get("name") or "Landscape"
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(pts))
    mesh.vertices.foreach_set("co", pts.astype(np.float32).ravel())
    mesh.loops.add(quads.size)
    mesh.loops.foreach_set("vertex_index", quads.astype(np.int32).ravel())
    mesh.polygons.add(len(quads))
    mesh.polygons.foreach_set("loop_start", (np.arange(len(quads)) * 4).astype(np.int32))
    mesh.polygons.foreach_set("loop_total", np.full(len(quads), 4, dtype=np.int32))
    uv = mesh.uv_layers.new(name="UVMap")
    u = (I / max(1, sx - 1)).ravel()
    v = 1.0 - (J / max(1, sy - 1)).ravel()
    uvs = np.stack([u, v], axis=1)[quads.ravel()]
    uv.data.foreach_set("uv", uvs.astype(np.float32).ravel())
    mesh.update(calc_edges=True)
    mesh.validate()
    if mesh.polygons and mesh.polygons[0].normal.z < 0:
        mesh.flip_normals()
    for old in list(collection.objects):  # re-sending replaces the terrain from the previous send
        if old.get("wildframe_from_unreal") and old.get("wildframe_landscape") \
                and old.name.split(".")[0] == name:
            old_mesh = old.data
            bpy.data.objects.remove(old)
            if old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh)
    obj = bpy.data.objects.new(name, mesh)
    obj["wildframe_from_unreal"] = True
    obj["wildframe_landscape"] = True
    if step == 1:  # sending it back reuses the exact Unreal grid
        obj["wildframe_landscape_size"] = [sx, sy]
    collection.objects.link(obj)
    obj.location = center.tolist()
    if hasattr(mesh, "shade_smooth"):
        mesh.shade_smooth()
    return obj, step
