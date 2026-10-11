# SPDX-License-Identifier: GPL-3.0-or-later
"""Import / export of models and scenes (FBX, glTF/GLB, OBJ, USD, Alembic, STL, PLY)."""

import os

import bpy

from .. import ctx
from ..registry import CommandError, command

FORMATS = ["fbx", "gltf", "glb", "obj", "usd", "usda", "usdc", "usdz", "abc", "stl", "ply"]


def _fmt(path, explicit=None):
    fmt = (explicit or os.path.splitext(path)[1].lstrip(".")).lower()
    if fmt not in FORMATS:
        raise CommandError("UNSUPPORTED_FORMAT", "Format '%s' is not supported (use %s)." % (fmt, ", ".join(FORMATS)))
    return fmt


def _op(*candidates):
    """First existing operator among dotted names (they moved between Blender versions)."""
    for name in candidates:
        mod, fn = name.split(".")
        op = getattr(getattr(bpy.ops, mod), fn)
        try:
            op.get_rna_type()
            return op
        except (KeyError, AttributeError):
            continue
    raise CommandError("IMPORTER_MISSING", "None of %s is available (is the add-on enabled?)." % ", ".join(candidates))


def import_file(path, fmt=None, options=None):
    """Import a file and return the list of new objects."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise CommandError("FILE_NOT_FOUND", "No file at %s." % path)
    fmt = _fmt(path, fmt)
    options = dict(options or {})
    before = set(bpy.data.objects.keys())
    with ctx.object_mode(), ctx.view3d():
        if fmt == "fbx":
            _op("import_scene.fbx")(filepath=path, **options)
        elif fmt in ("gltf", "glb"):
            _op("import_scene.gltf")(filepath=path, **options)
        elif fmt == "obj":
            _op("wm.obj_import", "import_scene.obj")(filepath=path, **options)
        elif fmt.startswith("usd"):
            _op("wm.usd_import")(filepath=path, **options)
        elif fmt == "abc":
            _op("wm.alembic_import")(filepath=path, **options)
        elif fmt == "stl":
            _op("wm.stl_import", "import_mesh.stl")(filepath=path, **options)
        elif fmt == "ply":
            _op("wm.ply_import", "import_mesh.ply")(filepath=path, **options)
    return [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]


def export_objects(objects, path, fmt=None, options=None, for_unreal=True, animation=False):
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fmt = _fmt(path, fmt)
    opts = {}
    if fmt == "fbx":
        opts = {"use_selection": True, "apply_scale_options": "FBX_SCALE_UNITS", "use_mesh_modifiers": True,
                "mesh_smooth_type": "FACE", "add_leaf_bones": False, "bake_anim": bool(animation),
                "path_mode": "COPY", "embed_textures": True}
        if for_unreal:
            # Keep Blender's default FBX axes: Unreal's FBX importer converts the file's axis system itself.
            # (rigs are exported from a centimetre copy by BRIDGE.SEND_TO_UNREAL; see commands/bridge.py)
            opts.update({"use_armature_deform_only": True, "use_tspace": True})
        if animation:
            # only the active action, every frame keyed, no curve simplification: exact timing in Unreal
            opts.update({"bake_anim_use_all_actions": False, "bake_anim_use_nla_strips": False,
                         "bake_anim_force_startend_keying": True, "bake_anim_simplify_factor": 0.0,
                         "bake_anim_step": 1.0})
    elif fmt in ("gltf", "glb"):
        opts = {"use_selection": True, "export_format": "GLB" if fmt == "glb" else "GLTF_SEPARATE",
                "export_apply": True, "export_animations": bool(animation), "export_yup": True}
    elif fmt == "obj":
        opts = {"export_selected_objects": True, "apply_modifiers": True, "path_mode": "COPY"}
    elif fmt.startswith("usd"):
        opts = {"selected_objects_only": True, "export_animation": bool(animation)}
    elif fmt == "abc":
        opts = {"selected": True}
    elif fmt == "stl":
        opts = {"export_selected_objects": True}
    elif fmt == "ply":
        opts = {"export_selected_objects": True}
    opts.update(options or {})
    with ctx.object_mode(), ctx.view3d():
        ctx.select_only(objects)
        if fmt == "fbx":
            _op("export_scene.fbx")(filepath=path, **opts)
        elif fmt in ("gltf", "glb"):
            _op("export_scene.gltf")(filepath=path, **opts)
        elif fmt == "obj":
            _op("wm.obj_export")(filepath=path, **opts)
        elif fmt.startswith("usd"):
            _op("wm.usd_export")(filepath=path, **opts)
        elif fmt == "abc":
            _op("wm.alembic_export")(filepath=path, **opts)
        elif fmt == "stl":
            _op("wm.stl_export", "export_mesh.stl")(filepath=path, **opts)
        elif fmt == "ply":
            _op("wm.ply_export", "export_mesh.ply")(filepath=path, **opts)
    if not os.path.exists(path):
        raise CommandError("EXPORT_FAILED", "Exporter finished but %s was not written." % path)
    return path


def resolve_selection(params):
    if params.get("names"):
        return ctx.get_objects(params["names"])
    if params.get("collection"):
        coll = bpy.data.collections.get(params["collection"])
        if coll is None:
            raise CommandError("COLLECTION_NOT_FOUND", "No collection %s." % params["collection"])
        return list(coll.all_objects)
    if params.get("selected", True) and bpy.context.selected_objects:
        return list(bpy.context.selected_objects)
    raise CommandError("NOTHING_TO_EXPORT", "Pass names, collection, or select objects first.")


@command("IO.IMPORT", "Import a model/scene file (FBX, glTF/GLB, OBJ, USD, Alembic, STL, PLY). Returns the new "
         "objects. 'options' are passed to Blender's importer.",
         params={"path": {"type": "string"}, "format": {"type": "string", "enum": FORMATS},
                 "options": {"type": "object", "default": {}}, "collection": {"type": "string"}},
         required=["path"], mutating=True)
def import_cmd(params):
    objs = import_file(params["path"], params.get("format"), params["options"])
    if params.get("collection") and objs:
        target = bpy.data.collections.get(params["collection"]) or bpy.data.collections.new(params["collection"])
        if target.name not in bpy.context.scene.collection.children:
            try:
                bpy.context.scene.collection.children.link(target)
            except RuntimeError:
                pass
        for obj in objs:
            for coll in list(obj.users_collection):
                coll.objects.unlink(obj)
            target.objects.link(obj)
    return {"file": params["path"], "created": [ctx.object_summary(o) for o in objs[:300]], "createdCount": len(objs)}


@command("IO.EXPORT", "Export objects (names, a collection, or the current selection) to FBX, glTF/GLB, OBJ, USD, "
         "Alembic, STL or PLY. for_unreal=true uses Unreal-friendly FBX axes/scale.",
         params={"path": {"type": "string"}, "format": {"type": "string", "enum": FORMATS},
                 "names": {"type": "array"}, "collection": {"type": "string"},
                 "selected": {"type": "boolean", "default": True},
                 "animation": {"type": "boolean", "default": False},
                 "for_unreal": {"type": "boolean", "default": True},
                 "options": {"type": "object", "default": {}}},
         required=["path"])
def export_cmd(params):
    objs = resolve_selection(params)
    path = export_objects(objs, params["path"], params.get("format"), params["options"],
                          params["for_unreal"], params["animation"])
    return {"file": path, "bytes": os.path.getsize(path), "objects": [o.name for o in objs]}
