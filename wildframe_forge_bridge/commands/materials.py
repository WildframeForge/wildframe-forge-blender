# SPDX-License-Identifier: GPL-3.0-or-later
"""Materials: list, PBR creation from texture files, assignment and Principled BSDF inputs."""

import os

import bpy

from .. import ctx
from ..registry import CommandError, command

TEXTURE_SLOTS = {
    "base_color": ("Base Color", "sRGB"),
    "roughness": ("Roughness", "Non-Color"),
    "metallic": ("Metallic", "Non-Color"),
    "normal": ("Normal", "Non-Color"),
    "emission": ("Emission Color", "sRGB"),
    "alpha": ("Alpha", "Non-Color"),
    "ao": (None, "Non-Color"),
    "orm": (None, "Non-Color"),  # packed Occlusion/Roughness/Metallic (Unreal / glTF convention)
}


def _principled(mat):
    if not mat.use_nodes:
        mat.use_nodes = True
    node = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if node is None:
        node = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None) \
            or mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        mat.node_tree.links.new(node.outputs["BSDF"], out.inputs["Surface"])
    return node


def _input(node, name):
    sock = node.inputs.get(name)
    if sock is None and name == "Emission Color":
        sock = node.inputs.get("Emission")
    if sock is None:
        raise CommandError("BAD_INPUT", "Principled BSDF has no input '%s'." % name,
                           {"inputs": [i.name for i in node.inputs]})
    return sock


def _image(path, colorspace):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise CommandError("FILE_NOT_FOUND", "Texture not found: %s" % path)
    img = bpy.data.images.load(path, check_existing=True)
    try:
        img.colorspace_settings.name = colorspace
    except TypeError:
        pass
    return img


@command("MATERIALS.LIST", "List materials with users and Principled BSDF base values.",
         params={"limit": {"type": "integer", "default": 300}})
def list_materials(params):
    out = []
    for mat in list(bpy.data.materials)[:params["limit"]]:
        row = {"name": mat.name, "users": mat.users, "useNodes": mat.use_nodes}
        if mat.use_nodes:
            node = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if node:
                row["baseColor"] = ctx.to_list(node.inputs["Base Color"].default_value)
                row["roughness"] = round(node.inputs["Roughness"].default_value, 4)
                row["metallic"] = round(node.inputs["Metallic"].default_value, 4)
            row["textures"] = [n.image.filepath for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image][:16]
        out.append(row)
    return {"count": len(bpy.data.materials), "materials": out}


@command("MATERIALS.CREATE_PBR",
         "Create (or rebuild) a Principled BSDF material from values and/or texture files: base_color, roughness, "
         "metallic, normal, emission, alpha, ao, orm (packed AO/Roughness/Metallic). Optionally assign it to objects.",
         params={"name": {"type": "string"},
                 "base_color": {"type": "array", "description": "[r,g,b] or [r,g,b,a] 0..1"},
                 "roughness": {"type": "number"}, "metallic": {"type": "number"},
                 "emission_strength": {"type": "number"},
                 "textures": {"type": "object", "default": {},
                              "description": "slot -> file path; slots: " + ", ".join(TEXTURE_SLOTS)},
                 "assign_to": {"type": "array", "default": []},
                 "overwrite": {"type": "boolean", "default": True}},
         required=["name"], mutating=True)
def create_pbr(params):
    mat = bpy.data.materials.get(params["name"])
    if mat is not None and not params["overwrite"]:
        raise CommandError("MATERIAL_EXISTS", "Material %s exists (overwrite=false)." % mat.name)
    if mat is None:
        mat = bpy.data.materials.new(params["name"])
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    if params.get("base_color") is not None:
        c = list(params["base_color"]) + [1.0] * (4 - len(params["base_color"]))
        bsdf.inputs["Base Color"].default_value = c[:4]
    if params.get("roughness") is not None:
        bsdf.inputs["Roughness"].default_value = params["roughness"]
    if params.get("metallic") is not None:
        bsdf.inputs["Metallic"].default_value = params["metallic"]
    if params.get("emission_strength") is not None:
        _input(bsdf, "Emission Strength").default_value = params["emission_strength"]
    y = 300
    used = {}
    for slot, path in params["textures"].items():
        if slot not in TEXTURE_SLOTS:
            raise CommandError("BAD_TEXTURE_SLOT", "Unknown slot %s (use %s)." % (slot, ", ".join(TEXTURE_SLOTS)))
        socket_name, colorspace = TEXTURE_SLOTS[slot]
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = _image(path, colorspace)
        tex.location = (-700, y)
        y -= 300
        used[slot] = tex.image.filepath
        if slot == "normal":
            nmap = nodes.new("ShaderNodeNormalMap")
            nmap.location = (-300, tex.location.y)
            links.new(tex.outputs["Color"], nmap.inputs["Color"])
            links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        elif slot == "orm":
            sep = nodes.new("ShaderNodeSeparateColor")
            sep.location = (-400, tex.location.y)
            links.new(tex.outputs["Color"], sep.inputs["Color"])
            links.new(sep.outputs[1], bsdf.inputs["Roughness"])
            links.new(sep.outputs[2], bsdf.inputs["Metallic"])
        elif slot == "ao":
            continue  # Blender has no AO input; kept in the material for export round-trips
        elif slot == "alpha":
            links.new(tex.outputs["Color"], bsdf.inputs["Alpha"])
            if hasattr(mat, "surface_render_method"):
                mat.surface_render_method = "DITHERED"
            elif hasattr(mat, "blend_method"):
                mat.blend_method = "HASHED"
        else:
            links.new(tex.outputs["Color"], _input(bsdf, socket_name))
    for name in params["assign_to"]:
        obj = ctx.get_object(name)
        if obj.data is None or not hasattr(obj.data, "materials"):
            continue
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    return {"material": mat.name, "textures": used, "assignedTo": params["assign_to"]}


@command("MATERIALS.ASSIGN", "Assign a material to objects (replace all slots, or set one slot index).",
         params={"material": {"type": "string"}, "names": {"type": "array"},
                 "slot": {"type": "integer", "description": "Slot index to set; omit to replace all slots"}},
         required=["material", "names"], mutating=True)
def assign(params):
    mat = bpy.data.materials.get(params["material"])
    if mat is None:
        raise CommandError("MATERIAL_NOT_FOUND", "No material %s." % params["material"])
    for obj in ctx.get_objects(params["names"]):
        if obj.data is None or not hasattr(obj.data, "materials"):
            raise CommandError("NO_MATERIAL_SLOTS", "%s (%s) cannot hold materials." % (obj.name, obj.type))
        if params.get("slot") is None:
            obj.data.materials.clear()
            obj.data.materials.append(mat)
        else:
            while len(obj.data.materials) <= params["slot"]:
                obj.data.materials.append(None)
            obj.data.materials[params["slot"]] = mat
    return {"material": mat.name, "names": params["names"]}


@command("MATERIALS.SET_INPUT", "Set a Principled BSDF input value on a material, e.g. input='Roughness' value=0.4, "
         "input='Base Color' value=[1,0,0,1].",
         params={"material": {"type": "string"}, "input": {"type": "string"}, "value": {}},
         required=["material", "input", "value"], mutating=True)
def set_input(params):
    mat = bpy.data.materials.get(params["material"])
    if mat is None:
        raise CommandError("MATERIAL_NOT_FOUND", "No material %s." % params["material"])
    sock = _input(_principled(mat), params["input"])
    value = params["value"]
    if isinstance(value, list) and len(value) == 3 and len(sock.default_value) == 4:
        value = value + [1.0]
    sock.default_value = value
    return {"material": mat.name, "input": sock.name, "value": ctx.jsonable(sock.default_value)}
