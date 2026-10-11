# SPDX-License-Identifier: GPL-3.0-or-later
"""Material translation between Blender and Unreal (WILDFRAME_MATERIAL_V1).

A material description is plain JSON stored in the exchange package next to the copied texture files:

    {"name": "Rock", "slot": "Rock", "index": 0,
     "blend": "opaque" | "masked" | "translucent", "twoSided": false, "alphaCutoff": 0.5, "uvScale": [1, 1],
     "baseColor": {"value": [r, g, b, a], "texture": "textures/rock_d.png"},
     "roughness": {"value": 0.5, "texture": "textures/rock_r.png", "channel": "r"},
     "metallic":  {"value": 0.0, "texture": ..., "channel": "r"},
     "ao":        {"texture": ..., "channel": "r"},
     "normal":    {"texture": ..., "strength": 1.0, "format": "opengl" | "directx"},
     "emissive":  {"value": [r, g, b], "texture": ..., "strength": 1.0},
     "opacity":   {"value": 1.0, "texture": ..., "channel": "a", "fromBaseColorAlpha": true},
     "warnings": [...]}

Blender uses OpenGL normal maps (green up); Unreal uses DirectX (green down). Each side converts on import.
"""

import os
import re
import shutil

import bpy

SCHEMA = "WILDFRAME_MATERIAL_V1"
COPY_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".bmp", ".tif", ".tiff", ".hdr"}
CHANNELS = {0: "r", 1: "g", 2: "b"}
PASS_THROUGH = {"REROUTE"}


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "Texture"


# ======================================================================= Blender -> description

class _Exporter:
    def __init__(self, folder):
        self.folder = folder
        self.tex_dir = os.path.join(folder, "textures")
        self.saved = {}  # image name -> relative path

    def save_image(self, image, own=False):
        """Copy/write an image into the package. own=True: a temporary image we created (saved in place)."""
        if own:
            os.makedirs(self.tex_dir, exist_ok=True)
            dest = self._unique(_safe(image.name), ".png")
            image.filepath_raw = dest
            image.file_format = "PNG"
            image.save()
            rel = os.path.relpath(dest, self.folder).replace("\\", "/")
            self.saved[image.name] = rel
            return rel
        if image.name in self.saved:
            return self.saved[image.name]
        os.makedirs(self.tex_dir, exist_ok=True)
        src = bpy.path.abspath(image.filepath_raw or image.filepath or "")
        ext = os.path.splitext(src)[1].lower()
        base = _safe(os.path.splitext(os.path.basename(src))[0] if src else image.name)
        rel = None
        if src and os.path.isfile(src) and not image.packed_file and not image.is_dirty and ext in COPY_EXTS:
            dest = self._unique(base, ext)
            shutil.copy2(src, dest)
            rel = os.path.relpath(dest, self.folder)
        else:
            # packed, generated, painted or an unusual format: write the pixels out as PNG (or EXR for float)
            is_float = image.is_float
            dest = self._unique(base, ".exr" if is_float else ".png")
            copy = image.copy()
            try:
                copy.filepath_raw = dest
                copy.file_format = "OPEN_EXR" if is_float else "PNG"
                copy.save()
            finally:
                bpy.data.images.remove(copy)
            rel = os.path.relpath(dest, self.folder)
        rel = rel.replace("\\", "/")
        self.saved[image.name] = rel
        return rel

    def _unique(self, base, ext):
        path = os.path.join(self.tex_dir, base + ext)
        n = 1
        while os.path.exists(path):
            path = os.path.join(self.tex_dir, "%s_%d%s" % (base, n, ext))
            n += 1
        return path


def _source(socket):
    """Follow a linked input socket back through reroutes. Returns (node, output socket) or (None, None)."""
    if not socket.is_linked:
        return None, None
    link = socket.links[0]
    node, out = link.from_node, link.from_socket
    while node.type in PASS_THROUGH and node.inputs[0].is_linked:
        link = node.inputs[0].links[0]
        node, out = link.from_node, link.from_socket
    return node, out


def _uv_scale(tex_node):
    node, _ = _source(tex_node.inputs["Vector"])
    if node is None or node.type != "MAPPING":
        return None
    scale = node.inputs["Scale"].default_value
    return [round(float(scale[0]), 5), round(float(scale[1]), 5)]


def _trace_texture(socket, warnings, label):
    """Return {"image", "channel", "uvScale"} for a socket fed by an image (optionally through Separate Color)."""
    node, out = _source(socket)
    if node is None:
        return None
    channel = None
    if node.type in ("SEPARATE_COLOR", "SEPRGB", "SEPARATE_RGB"):
        channel = CHANNELS.get(list(node.outputs).index(out), "r")
        node, out = _source(node.inputs[0])
        if node is None:
            return None
    if node.type == "TEX_IMAGE" and node.image is not None:
        if out.name == "Alpha":
            channel = "a"
        return {"image": node.image, "channel": channel or "rgb", "uvScale": _uv_scale(node)}
    warnings.append("%s is driven by a '%s' node, which has no Unreal equivalent; enable bake_procedural to bake "
                    "it to a texture." % (label, node.bl_idname))
    return {"unsupported": node.bl_idname, "label": label}


def _principled(mat):
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) \
        or next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is not None:
        node, _ = _source(out.inputs["Surface"])
        if node is not None and node.type == "BSDF_PRINCIPLED":
            return node
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def _socket(bsdf, *names):
    for name in names:
        s = bsdf.inputs.get(name)
        if s is not None:
            return s
    return None


def describe(mat, folder, exporter=None, slot_index=0):
    """WILDFRAME_MATERIAL_V1 description of a Blender material. Textures are copied into <folder>/textures."""
    exporter = exporter or _Exporter(folder)
    warnings = []
    desc = {"schema": SCHEMA, "name": mat.name if mat else "Default", "slot": mat.name if mat else "None",
            "index": slot_index, "blend": "opaque", "twoSided": False, "alphaCutoff": 0.5, "uvScale": [1.0, 1.0],
            "warnings": warnings}
    if mat is None:
        desc["baseColor"] = {"value": [0.8, 0.8, 0.8, 1.0]}
        return desc
    bsdf = _principled(mat)
    if bsdf is None:
        c = list(mat.diffuse_color)
        desc["baseColor"] = {"value": [round(float(v), 5) for v in c]}
        desc["roughness"] = {"value": float(mat.roughness)}
        desc["metallic"] = {"value": float(mat.metallic)}
        warnings.append("No Principled BSDF in '%s'; only the viewport colour was transferred (enable "
                        "bake_procedural to bake the full shader)." % mat.name)
        desc["_needsBake"] = ["Shader"]
        return desc
    uv_scales = []

    needs_bake = []
    desc["_needsBake"] = needs_bake

    def tex_entry(trace):
        if trace and "unsupported" in trace:
            needs_bake.append(trace["label"])
        if not trace or "image" not in trace:
            return {}
        if trace.get("uvScale"):
            uv_scales.append(trace["uvScale"])
        return {"texture": exporter.save_image(trace["image"])}

    # base colour (+ alpha)
    s = _socket(bsdf, "Base Color")
    entry = {"value": [round(float(v), 5) for v in s.default_value]}
    t = _trace_texture(s, warnings, "Base Color")
    entry.update(tex_entry(t))
    if t and "image" in t:
        entry["value"] = [1.0, 1.0, 1.0, 1.0]
    desc["baseColor"] = entry

    for key, names in (("roughness", ("Roughness",)), ("metallic", ("Metallic",))):
        s = _socket(bsdf, *names)
        entry = {"value": round(float(s.default_value), 5)}
        t = _trace_texture(s, warnings, names[0])
        if t and "image" in t:
            entry.update(tex_entry(t))
            entry["channel"] = t["channel"] if t["channel"] != "rgb" else "r"
            entry["value"] = 1.0
        desc[key] = entry

    # normal: Normal Map node -> image
    s = _socket(bsdf, "Normal")
    node, _ = _source(s)
    if node is not None and node.type == "NORMAL_MAP":
        t = _trace_texture(node.inputs["Color"], warnings, "Normal")
        if t and "image" in t:
            desc["normal"] = dict(tex_entry(t), strength=round(float(node.inputs["Strength"].default_value), 5),
                                  format="opengl")
        if node.space != "TANGENT":
            warnings.append("Normal map space %s converted as tangent space." % node.space)
    elif node is not None:
        needs_bake.append("Normal")
        warnings.append("Normal is driven by a '%s' node; enable bake_procedural to bake it to a normal map."
                        % node.bl_idname)

    # emission
    s_col = _socket(bsdf, "Emission Color", "Emission")
    s_str = _socket(bsdf, "Emission Strength")
    strength = float(s_str.default_value) if s_str else 1.0
    col = [round(float(v), 5) for v in s_col.default_value][:3] if s_col else [0, 0, 0]
    t = _trace_texture(s_col, warnings, "Emission") if s_col else None
    if (t and "image" in t) or (strength > 0 and any(v > 0 for v in col)):
        entry = {"value": [1.0, 1.0, 1.0] if t and "image" in t else col, "strength": round(strength, 5)}
        entry.update(tex_entry(t))
        desc["emissive"] = entry

    # alpha / opacity
    s = _socket(bsdf, "Alpha")
    alpha = float(s.default_value)
    t = _trace_texture(s, warnings, "Alpha")
    if t and "image" in t:
        base_img = None
        bnode, _ = _source(_socket(bsdf, "Base Color"))
        if bnode is not None and bnode.type == "TEX_IMAGE":
            base_img = bnode.image
        if base_img is not None and t["image"] == base_img and t["channel"] == "a":
            desc["opacity"] = {"value": 1.0, "fromBaseColorAlpha": True}
        else:
            desc["opacity"] = dict(tex_entry(t), value=1.0, channel=t["channel"] if t["channel"] != "rgb" else "r")
    elif alpha < 0.999:
        desc["opacity"] = {"value": round(alpha, 5)}
    if "opacity" in desc:
        method = getattr(mat, "surface_render_method", None) or getattr(mat, "blend_method", "")
        desc["blend"] = "translucent" if method in ("BLENDED", "BLEND") else "masked"
        desc["alphaCutoff"] = round(float(getattr(mat, "alpha_threshold", 0.5)), 4)
    desc["twoSided"] = not bool(getattr(mat, "use_backface_culling", False))

    # ambient occlusion has no Principled input: pick up an image node labelled/named AO or ORM if present
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image is not None and re.search(r"(^|[^a-z])(ao|occlusion|orm)([^a-z]|$)",
                                                                         (n.label + " " + n.name + " " + n.image.name).lower()):
            desc["ao"] = {"texture": exporter.save_image(n.image), "channel": "r"}
            break

    for name, label in (("Subsurface Weight", "Subsurface"), ("Transmission Weight", "Transmission"),
                        ("Coat Weight", "Coat"), ("Sheen Weight", "Sheen")):
        s = bsdf.inputs.get(name)
        if s is not None and (s.is_linked or float(s.default_value) > 0.001):
            warnings.append("%s is not transferred (no equivalent in the Wildframe Forge PBR material)." % label)
    if uv_scales:
        desc["uvScale"] = uv_scales[0]
        if any(sc != uv_scales[0] for sc in uv_scales):
            warnings.append("Textures use different UV scales; the first one (%s) was used." % uv_scales[0])
    return desc


def describe_objects(objects, folder, bake=False, bake_size=1024):
    """Descriptions for every material used by the objects, in slot order of the first user. With bake=True,
    inputs driven by procedural nodes (and non-Principled shaders) are baked to textures with Cycles."""
    exporter = _Exporter(folder)
    out, seen = [], set()
    for obj in objects:
        if obj.type != "MESH":
            continue
        for index, slot in enumerate(obj.material_slots):
            mat = slot.material
            key = mat.name if mat else None
            if key in seen:
                continue
            seen.add(key)
            desc = describe(mat, folder, exporter, index)
            todo = desc.pop("_needsBake", [])
            if todo and bake and mat is not None:
                bake_into(desc, obj, index, mat, todo, exporter, bake_size)
            elif todo and not bake:
                pass
            out.append(desc)
    return out


# ======================================================================= procedural bake (Cycles)

BAKE_SOCKETS = {"Base Color": ("baseColor", "sRGB"), "Roughness": ("roughness", "Non-Color"),
                "Metallic": ("metallic", "Non-Color"), "Emission": ("emissive", "sRGB"),
                "Alpha": ("opacity", "Non-Color")}


def _bsdf_socket_for(bsdf, label):
    if label == "Emission":
        return bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
    return bsdf.inputs.get(label)


def bake_into(desc, obj, slot_index, mat, labels, exporter, size=1024):
    """Bake the listed Principled inputs (or the whole shader) of one material slot into textures."""
    warnings = desc.setdefault("warnings", [])
    if obj.type != "MESH" or not obj.data.uv_layers:
        warnings.append("Cannot bake '%s': %s has no UV map." % (mat.name, obj.name))
        return
    scene = bpy.context.scene
    saved = {"engine": scene.render.engine, "slots": [s.material for s in obj.material_slots],
             "active": bpy.context.view_layer.objects.active,
             "selected": [o for o in bpy.context.view_layer.objects if o.select_get()]}
    temps, images = [], []
    try:
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 8
        try:
            scene.cycles.device = "CPU"
        except Exception:  # noqa: BLE001
            pass
        for o in saved["selected"]:
            o.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        whole_shader = labels == ["Shader"]
        jobs = []
        if whole_shader:
            jobs = [("DIFFUSE", "baseColor", "sRGB"), ("ROUGHNESS", "roughness", "Non-Color"),
                    ("NORMAL", "normal", "Non-Color")]
        else:
            for label in labels:
                if label == "Normal":
                    jobs.append(("NORMAL", "normal", "Non-Color"))
                elif label in BAKE_SOCKETS:
                    jobs.append(("EMIT_" + label, BAKE_SOCKETS[label][0], BAKE_SOCKETS[label][1]))
        for bake_type, key, colorspace in jobs:
            img = bpy.data.images.new("RX_Bake_%s_%s" % (mat.name, key), size, size, alpha=False,
                                      float_buffer=False, is_data=colorspace == "Non-Color")
            images.append(img)
            # temp copies of every slot material, each with the target image as the active node
            for i, slot in enumerate(obj.material_slots):
                src = saved["slots"][i]
                if src is None:
                    continue
                tmp = src.copy()
                temps.append(tmp)
                slot.material = tmp
                nodes, links = tmp.node_tree.nodes, tmp.node_tree.links
                tex = nodes.new("ShaderNodeTexImage")
                tex.image = img
                nodes.active = tex
                if i == slot_index and bake_type.startswith("EMIT_"):
                    label = bake_type[5:]
                    bsdf = _principled(tmp)
                    sock = _bsdf_socket_for(bsdf, label)
                    out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) \
                        or nodes.new("ShaderNodeOutputMaterial")
                    emit = nodes.new("ShaderNodeEmission")
                    if sock.is_linked:
                        links.new(sock.links[0].from_socket, emit.inputs["Color"])
                    else:
                        v = sock.default_value
                        emit.inputs["Color"].default_value = (list(v) + [1.0] * 4)[:4] if hasattr(v, "__len__") \
                            else (v, v, v, 1.0)
                    links.new(emit.outputs["Emission"], out.inputs["Surface"])
            kwargs = {"type": "EMIT" if bake_type.startswith("EMIT_") else bake_type, "margin": 8,
                      "use_clear": True}
            if bake_type == "DIFFUSE":
                kwargs["pass_filter"] = {"COLOR"}
            if bake_type == "NORMAL":
                kwargs["normal_space"] = "TANGENT"
            from . import ctx
            with ctx.object_mode(), ctx.view3d():
                bpy.ops.object.bake(**kwargs)
            for i, slot in enumerate(obj.material_slots):
                slot.material = saved["slots"][i]
            rel = exporter.save_image(img, own=True)
            if key == "baseColor":
                desc["baseColor"] = {"value": [1, 1, 1, 1], "texture": rel}
            elif key in ("roughness", "metallic"):
                desc[key] = {"value": 1.0, "texture": rel, "channel": "r"}
            elif key == "normal":
                desc["normal"] = {"texture": rel, "strength": 1.0, "format": "opengl"}
            elif key == "emissive":
                desc["emissive"] = dict(desc.get("emissive") or {"strength": 1.0}, value=[1, 1, 1], texture=rel)
            elif key == "opacity":
                desc["opacity"] = {"value": 1.0, "texture": rel, "channel": "r"}
                desc["blend"] = desc.get("blend") if desc.get("blend") != "opaque" else "masked"
        baked = [j[1] for j in jobs]
        desc["baked"] = baked
        desc["warnings"] = [w for w in warnings if "bake_procedural" not in w]
    except Exception as error:  # noqa: BLE001
        warnings.append("Baking '%s' failed: %s" % (mat.name, error))
    finally:
        for i, slot in enumerate(obj.material_slots):
            slot.material = saved["slots"][i]
        for tmp in temps:
            if tmp.users == 0:
                bpy.data.materials.remove(tmp)
        for img in images:
            bpy.data.images.remove(img)
        scene.render.engine = saved["engine"]
        obj.select_set(False)
        for o in saved["selected"]:
            if o.name in bpy.context.view_layer.objects:
                o.select_set(True)
        bpy.context.view_layer.objects.active = saved["active"]


# ======================================================================= description -> Blender

def _load_image(folder, rel, colorspace):
    path = os.path.join(folder, rel)
    if not os.path.isfile(path):
        return None
    img = bpy.data.images.load(path, check_existing=True)
    try:
        img.colorspace_settings.name = colorspace
    except TypeError:
        pass
    return img


def build(desc, folder, name=None):
    """Create a Blender material from a WILDFRAME_MATERIAL_V1 description. Returns (material, warnings)."""
    warnings = list(desc.get("warnings") or [])
    mat = bpy.data.materials.new(name or desc.get("name") or "Material")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    for n in list(nodes):
        nodes.remove(n)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (500, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    uv = desc.get("uvScale") or [1.0, 1.0]
    mapping = None
    if abs(uv[0] - 1) > 1e-4 or abs(uv[1] - 1) > 1e-4:
        coord = nodes.new("ShaderNodeTexCoord")
        coord.location = (-1300, 0)
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-1100, 0)
        mapping.inputs["Scale"].default_value = (uv[0], uv[1], 1.0)
        links.new(coord.outputs["UV"], mapping.inputs["Vector"])
    images = {}
    row = [400]

    def image_node(rel, colorspace, label):
        key = (rel, colorspace)
        if key in images:
            return images[key]
        img = _load_image(folder, rel, colorspace)
        if img is None:
            warnings.append("Texture %s is missing from the package." % rel)
            return None
        n = nodes.new("ShaderNodeTexImage")
        n.image = img
        n.label = label
        n.location = (-800, row[0])
        row[0] -= 280
        if mapping is not None:
            links.new(mapping.outputs["Vector"], n.inputs["Vector"])
        images[key] = n
        return n

    def channel_out(tex, channel):
        if channel in (None, "rgb"):
            return tex.outputs["Color"]
        if channel == "a":
            return tex.outputs["Alpha"]
        sep = nodes.new("ShaderNodeSeparateColor")
        sep.location = (tex.location.x + 300, tex.location.y)
        links.new(tex.outputs["Color"], sep.inputs["Color"])
        return sep.outputs["rgb".index(channel)]

    base = desc.get("baseColor") or {}
    if base.get("value"):
        v = list(base["value"]) + [1.0] * (4 - len(base["value"]))
        bsdf.inputs["Base Color"].default_value = v[:4]
    base_tex = image_node(base["texture"], "sRGB", "Base Color") if base.get("texture") else None
    if base_tex is not None:
        tint = base.get("value") or [1, 1, 1, 1]
        if any(abs(c - 1.0) > 1e-4 for c in tint[:3]):
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            mix.location = (-300, 300)
            links.new(base_tex.outputs["Color"], mix.inputs[6])
            mix.inputs[7].default_value = list(tint[:3]) + [1.0]
            links.new(mix.outputs[2], bsdf.inputs["Base Color"])
        else:
            links.new(base_tex.outputs["Color"], bsdf.inputs["Base Color"])

    for key, socket in (("roughness", "Roughness"), ("metallic", "Metallic")):
        e = desc.get(key) or {}
        if "value" in e:
            bsdf.inputs[socket].default_value = float(e["value"])
        if e.get("texture"):
            tex = image_node(e["texture"], "Non-Color", socket)
            if tex is not None:
                src = channel_out(tex, e.get("channel", "r"))
                scale = float(e.get("value", 1.0))
                if abs(scale - 1.0) > 1e-4:
                    m = nodes.new("ShaderNodeMath")
                    m.operation = "MULTIPLY"
                    m.inputs[1].default_value = scale
                    m.location = (-150, tex.location.y)
                    links.new(src, m.inputs[0])
                    src = m.outputs[0]
                links.new(src, bsdf.inputs[socket])

    n = desc.get("normal") or {}
    if n.get("texture"):
        tex = image_node(n["texture"], "Non-Color", "Normal")
        if tex is not None:
            nmap = nodes.new("ShaderNodeNormalMap")
            nmap.location = (-200, -500)
            nmap.inputs["Strength"].default_value = float(n.get("strength", 1.0))
            color = tex.outputs["Color"]
            if n.get("format", "opengl") == "directx":  # flip green for Blender
                sep = nodes.new("ShaderNodeSeparateColor")
                inv = nodes.new("ShaderNodeMath")
                comb = nodes.new("ShaderNodeCombineColor")
                inv.operation = "SUBTRACT"
                inv.inputs[0].default_value = 1.0
                sep.location, inv.location, comb.location = (-520, -500), (-380, -560), (-260, -460)
                nmap.location = (-100, -500)
                links.new(color, sep.inputs["Color"])
                links.new(sep.outputs[0], comb.inputs[0])
                links.new(sep.outputs[1], inv.inputs[1])
                links.new(inv.outputs[0], comb.inputs[1])
                links.new(sep.outputs[2], comb.inputs[2])
                color = comb.outputs["Color"]
            links.new(color, nmap.inputs["Color"])
            links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

    e = desc.get("emissive")
    if e:
        sock_c = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        sock_s = bsdf.inputs.get("Emission Strength")
        v = list(e.get("value") or [1, 1, 1])[:3]
        sock_c.default_value = v + [1.0]
        if sock_s is not None:
            sock_s.default_value = float(e.get("strength", 1.0))
        if e.get("texture"):
            tex = image_node(e["texture"], "sRGB", "Emissive")
            if tex is not None:
                links.new(tex.outputs["Color"], sock_c)

    o = desc.get("opacity")
    if o:
        if o.get("fromBaseColorAlpha") and base_tex is not None:
            links.new(base_tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        elif o.get("texture"):
            tex = image_node(o["texture"], "Non-Color", "Opacity")
            if tex is not None:
                links.new(channel_out(tex, o.get("channel", "r")), bsdf.inputs["Alpha"])
        else:
            bsdf.inputs["Alpha"].default_value = float(o.get("value", 1.0))
        blended = desc.get("blend") == "translucent"
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED" if blended else "DITHERED"
        elif hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND" if blended else "CLIP"
        if hasattr(mat, "alpha_threshold"):
            mat.alpha_threshold = float(desc.get("alphaCutoff", 0.5))
    a = desc.get("ao")
    if a and a.get("texture"):
        tex = image_node(a["texture"], "Non-Color", "AO")  # kept for round trips; Cycles/EEVEE compute AO themselves
        if tex is not None:
            tex.name = "AO"
    mat.use_backface_culling = not bool(desc.get("twoSided", False))
    return mat, warnings


def _desc_key(desc):
    """Identity of a material description, ignoring which slot of which mesh it sits on."""
    import json
    return json.dumps({k: v for k, v in desc.items() if k not in ("slot", "index", "warnings")}, sort_keys=True,
                      default=str)


def apply_to_objects(objects, descriptions, folder, cache=None):
    """Replace the importer's placeholder materials with materials built from the descriptions.
    cache (a dict shared across the items of one package) reuses one Blender material for identical descriptions."""
    built, warnings = {}, []
    cache = {} if cache is None else cache
    by_name = {d.get("name"): d for d in descriptions}
    by_index = {d.get("index", i): d for i, d in enumerate(descriptions)}
    placeholders = set()
    for obj in objects:
        if obj.type not in ("MESH",):
            continue
        for index, slot in enumerate(obj.material_slots):
            old = slot.material
            desc = None
            if old is not None:
                stem = re.sub(r"\.\d{3}$", "", old.name)
                desc = by_name.get(stem) or by_name.get(old.name)
            desc = desc or by_index.get(index)
            if desc is None:
                continue
            key = desc.get("name")
            if key not in built:
                ident = _desc_key(desc)
                mat = cache.get(ident)
                try:
                    alive = mat is not None and mat.name in bpy.data.materials
                except ReferenceError:  # the cached material was removed meanwhile
                    alive = False
                if not alive:
                    mat, w = build(desc, folder)
                    warnings.extend("%s: %s" % (key, x) for x in w)
                    cache[ident] = mat
                built[key] = mat
            if old is not None and old is not built[key]:
                placeholders.add(old)
            slot.material = built[key]
    for old in placeholders:
        if old.users == 0:
            bpy.data.materials.remove(old)
    for key, mat in built.items():  # drop the ".001" the importer's placeholder forced on us
        if key and mat.name != key and key not in bpy.data.materials:
            mat.name = key
    return {"materials": [m.name for m in built.values()], "warnings": warnings}
