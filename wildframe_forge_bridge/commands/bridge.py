# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender <-> Unreal transfers through the shared exchange folder."""

import os
import re

import bpy

from .. import ctx, exchange, instances, matxfer, prefs, scenexfer, terrainxfer
from ..registry import CommandError, command
from . import io as io_cmds


COLLISION_PREFIXES = ("UCX_", "UBX_", "USP_", "UCP_")  # Unreal custom collision naming
GEOMETRY_TYPES = ("MESH", "CURVE", "SURFACE", "FONT", "META")


def _safe(name):
    """Unreal-safe asset name: accents transliterated (Ünïcödé -> Unicode), other symbols become '_'."""
    import unicodedata
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9_]+", "_", ascii_name).strip("_") or "Asset"


def _strip_dup_suffixes(pairs, taken=()):
    """pairs: (sent name, Blender name). Map sent names whose Blender name ends in a duplicate suffix (.001) to the
    name without it, when no other sent name is (or would become) that name and nothing in taken (the names of
    other Blender objects/materials) is called that, so a different object's asset is never overwritten."""
    names = {n for n, _ in pairs} | set(taken)
    wanted = {}
    for sent, original in pairs:
        m = re.match(r"^(.*)\.\d{3}$", original or "")
        if not m:
            continue
        stem = _safe(m.group(1)) if sent != original else m.group(1)
        if stem and stem not in names:
            wanted.setdefault(stem, set()).add(sent)
    return {next(iter(v)): k for k, v in wanted.items() if len(v) == 1}


def _kind(objs, animation):
    if any(o.type == "ARMATURE" for o in objs):
        return "animation" if animation and all(o.type == "ARMATURE" for o in objs) else "skeletal_mesh"
    return "static_mesh"


def _roots(objs):
    names = {o.name for o in objs}
    return [o for o in objs if not (o.parent and o.parent.name in names)]


def _unreal_to_blender_matrix(item):
    """Blender world matrix for an Unreal placement (cm, left-handed) given as axes + scale + location."""
    from mathutils import Matrix, Vector
    loc = item.get("unrealLocationCm")
    if not loc:
        return None
    axes = item.get("unrealAxes")  # [forward, right, up] world vectors of the actor's local X, Y, Z
    scale = item.get("unrealScale") or [1.0, 1.0, 1.0]
    mat = Matrix.Identity(4)
    if axes:
        flip = lambda v: Vector((v[0], -v[1], v[2]))  # noqa: E731
        cols = (flip(axes[0]) * scale[0], -flip(axes[1]) * scale[1], flip(axes[2]) * scale[2])
        for c in range(3):
            for r in range(3):
                mat[r][c] = cols[c][r]
    mat[0][3], mat[1][3], mat[2][3] = loc[0] / 100.0, -loc[1] / 100.0, loc[2] / 100.0
    return mat


def _max_x(obj):
    if obj.type != "MESH":
        return obj.matrix_world.translation.x
    from mathutils import Vector
    return max((obj.matrix_world @ Vector(c)).x for c in obj.bound_box)


def _width(objs):
    xs = []
    for o in objs:
        if o.type == "MESH":
            xs.extend((o.matrix_world @ __import__("mathutils").Vector(c)).x for c in o.bound_box)
    return (max(xs) - min(xs)) if xs else 1.0


def _normalize_rigs(objs, warnings):
    """Unreal FBX rigs arrive in centimetres: either EMPTY(scale 0.01) > ARMATURE > meshes (skeletal meshes) or an
    ARMATURE with scale 0.01 itself (animations). Turn that into a clean armature named after the asset, at scale 1
    with bones in metres, and convert its keyframes to match (what Blender animators expect, and what round-trips
    back to Unreal exactly)."""
    for arm in [o for o in objs if o.type == "ARMATURE"]:
        top = arm.parent if (arm.parent is not None and arm.parent.type == "EMPTY") else None
        # Blender's FBX importer turns Unreal's root bone into the armature object: remember its name so the rig
        # can be sent back with the exact same skeleton
        arm["wildframe_root_bone"] = re.sub(r"\.\d{3}$", "", arm.name)
        parent_scale = top.matrix_world.to_scale().x if top else 1.0
        own_scale = arm.scale.x
        if top is not None:
            name = top.name
            for child in list(top.children):
                w = child.matrix_world.copy()
                child.parent = None if child is arm else arm
                child.matrix_world = w
            objs.remove(top)
            bpy.data.objects.remove(top)
            arm.name = name
            arm.data.name = name
        world = arm.matrix_world.to_scale()
        s = world.x
        if abs(s - 1.0) < 1e-6 or abs(world.y - s) > 1e-6 or abs(world.z - s) > 1e-6:
            continue
        action = arm.animation_data.action if arm.animation_data else None
        slot = getattr(arm.animation_data, "action_slot", None) if action is not None else None
        if action is not None:  # detach while applying the scale, or the scale keys would override it
            current = tuple(arm.scale)
            arm.animation_data.action = None
            arm.scale = current
        rig = [arm] + list(arm.children_recursive)
        with ctx.object_mode(), ctx.view3d():
            ctx.select_only(rig)
            bpy.context.view_layer.objects.active = arm
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        if action is not None:
            arm.animation_data.action = action
            if slot is not None:
                try:
                    arm.animation_data.action_slot = slot
                except Exception:  # noqa: BLE001
                    pass
            for fc in _fcurves(action):
                if fc.data_path.startswith("pose.bones") and fc.data_path.endswith(".location"):
                    factor = s                      # bone offsets are in armature units
                elif fc.data_path == "location":
                    factor = parent_scale           # object location is in the (removed) parent's units
                elif fc.data_path == "scale":
                    factor = 1.0 / own_scale if own_scale else 1.0
                else:
                    continue
                if abs(factor - 1.0) < 1e-9:
                    continue
                for kp in fc.keyframe_points:
                    kp.co.y *= factor
                    kp.handle_left.y *= factor
                    kp.handle_right.y *= factor
                fc.update()
        for o in rig:
            o["wildframe_asset"] = arm.name


def _fcurves(action):
    try:
        curves = list(action.fcurves)
        if curves:
            return curves
    except (AttributeError, TypeError):
        pass
    curves = []  # Blender 4.4+ slotted actions
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                curves.extend(bag.fcurves)
    return curves


def _export_rig_name(arm, warnings=None, deform_only=False):
    """Name the armature object must have in the FBX so Unreal builds the right skeleton:
    - one top-level bone: 'Armature' (Unreal drops that node and uses the bone as root);
    - several top-level bones (e.g. a rig that came from Unreal, whose root bone Blender turned into the
      object): the remembered root-bone name, so the object itself becomes Unreal's single root bone."""
    exported = [b for b in arm.data.bones if b.use_deform or not deform_only or
                any(c.use_deform for c in b.children_recursive)]
    tops = [b for b in exported if b.parent is None or b.parent not in exported]
    if len(tops) == 1 and not arm.get("wildframe_root_bone"):
        return "Armature"
    root = arm.get("wildframe_root_bone") or "root"
    taken = {b.name.lower() for b in arm.data.bones}
    while not arm.get("wildframe_root_bone") and root.lower() in taken:  # Unreal bone names ignore case
        root = "rig_" + root
    if not arm.get("wildframe_root_bone") and warnings is not None:
        warnings.append("%s has %d top-level bones; Unreal needs one root, so the armature becomes root bone '%s'."
                        % (arm.name, len(tops), root))
    return root


def _armature_names_for_unreal(members, warnings=None, deform_only=False):
    """Temporarily rename the exported armature (see _export_rig_name). Returns [(object, name)] to restore."""
    arms = [o for o in members if o.type == "ARMATURE"]
    if len(arms) != 1:
        return []
    target = _export_rig_name(arms[0], warnings, deform_only)
    if arms[0].name == target:
        return []
    out = [(arms[0], arms[0].name)]
    other = bpy.data.objects.get(target)
    if other is not None:
        out.append((other, other.name))
        other.name = "WildframeTmp_" + target
    arms[0].name = target
    return out


def _restore_names(renamed):
    for obj, name in renamed:  # the armature first (frees "Armature"), then whatever held that name before
        obj.name = name


def _apply_animation(objs, item, params, warnings):
    """An animation from Unreal: put its action on the matching rig already in the scene (same Unreal skeleton or
    target_armature) and drop the imported duplicate rig. Without a match the imported rig is kept."""
    arms = [o for o in objs if o.type == "ARMATURE"]
    if not arms:
        return None
    src = arms[0]
    action = src.animation_data.action if src.animation_data else None
    if action is None:
        warnings.append("%s: the file had no animation." % item.get("name"))
        return None
    action.name = _safe(item.get("name") or action.name)
    action.use_fake_user = True
    if item.get("frames"):
        action["wildframe_frames"] = int(item["frames"])
        action["wildframe_fps"] = float(item.get("fps") or bpy.context.scene.render.fps)
    target = bpy.data.objects.get(params["target_armature"]) if params.get("target_armature") else None
    if target is None and item.get("unrealSkeleton"):
        target = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE" and o not in objs
                       and o.get("wildframe_unreal_skeleton") == item["unrealSkeleton"]), None)
    scene = bpy.context.scene
    start, end = _action_range(action)
    scene.frame_start, scene.frame_end = start, end
    if target is None:
        return {"action": action.name, "armature": src.name, "appliedTo": None}
    if any(fc.data_path == "location" for fc in _fcurves(action)) and target.location.length > 1e-6:
        warnings.append("%s keys the root (root motion), so %s now plays from the root's animated position."
                        % (action.name, target.name))
    added = _add_missing_bones(src, target)
    baked_action, baked = _bake_world(src, target, action, item)
    if baked_action is not None:
        wanted = action.name
        bpy.data.actions.remove(action)
        baked_action.name = wanted
        action = baked_action
    for o in [src] + list(src.children_recursive):
        if o in objs:
            objs.remove(o)
        bpy.data.objects.remove(o)
    return {"action": action.name, "armature": target.name, "appliedTo": target.name,
            "bakedBones": baked, "addedBones": added}


def _add_missing_bones(src, dst):
    """Animations from Unreal key every bone of the Skeleton asset, but a rig made from one skeletal mesh only has
    that mesh's bones (e.g. no weapon/IK bones). Add the missing bones (same rest pose, same parents) so nothing
    in the animation is lost and it goes back to Unreal complete."""
    missing = [b.name for b in src.data.bones if b.name not in dst.data.bones]
    if not missing:
        return []
    rel = dst.matrix_world.inverted() @ src.matrix_world
    src_bones = {b.name: (rel @ b.head_local, rel @ b.tail_local, b.matrix_local, b.parent.name if b.parent else None)
                 for b in src.data.bones if b.name in missing}
    with ctx.object_mode(), ctx.view3d():
        ctx.select_only([dst])
        bpy.context.view_layer.objects.active = dst
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            edit = dst.data.edit_bones
            for name in missing:  # parents come before children in Blender's bone list
                head, tail, mloc, parent = src_bones[name]
                eb = edit.new(name)
                eb.head, eb.tail = head, tail
                eb.align_roll((rel.to_3x3() @ mloc.to_3x3()).col[2])
                eb.use_deform = False
                if parent and parent in edit:
                    eb.parent = edit[parent]
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")
    return missing


def _bake_world(src, dst, src_action, item):
    """Put src's animation on dst by matching every bone's WORLD transform on every frame, then keying dst's own
    channels (its rest pose, hierarchy and rotation modes). src's armature object stands in for the Unreal root bone
    (Blender's importer turns that bone into the object); dst may have it as a real bone. Returns (action, bones)."""
    scene = bpy.context.scene
    start, end = _action_range(src_action)
    if src_action.get("wildframe_frames") is None and item.get("frames"):
        end = start + int(item["frames"])
    root_name = src.get("wildframe_root_bone")
    pairs = []  # (dst pose bone, source getter)
    for pb in dst.pose.bones:
        if pb.name in src.pose.bones:
            pairs.append((pb, ("bone", pb.name)))
        elif root_name and pb.name.lower() == root_name.lower():
            pairs.append((pb, ("object", None)))
    if not pairs:
        return None, []
    # dst also has its root as the object (a rig that came from Unreal): carry root motion on the object itself
    object_root = bool(root_name) and not any(g[0] == "object" for _, g in pairs) and \
        (dst.get("wildframe_root_bone") or "").lower() == root_name.lower()
    object_keys = []
    # The imported rig sits at the origin, so its world space IS the animation's armature space: map it straight
    # onto dst's armature space (the animation plays wherever the user put dst).
    from mathutils import Matrix
    dst_inv = Matrix.Identity(4)
    rest = {pb.name: pb.bone.matrix_local for pb, _ in pairs}
    order = [pb for pb in dst.pose.bones if pb.name in rest]  # Blender lists parents before children
    keys = {pb.name: [] for pb in order}
    saved_frame = scene.frame_current
    dst_action = dst.animation_data.action if dst.animation_data else None
    if dst.animation_data:
        dst.animation_data.action = None
    getters = dict((pb.name, g) for pb, g in pairs)
    for f in range(start, end + 1):
        scene.frame_set(f)
        if object_root:
            object_keys.append((f, src.matrix_world.copy()))
            dst_inv = src.matrix_world.inverted()  # dst object will follow src's root on this frame
        world = {}
        for pb in order:
            kind, name = getters[pb.name]
            m = src.matrix_world.copy() if kind == "object" else src.matrix_world @ src.pose.bones[name].matrix
            world[pb.name] = dst_inv @ m  # desired pose matrix in dst armature space
        for pb in order:
            m = world[pb.name]
            parent = pb.parent
            while parent is not None and parent.name not in world:
                parent = parent.parent
            if parent is None:
                basis = rest[pb.name].inverted() @ m
            else:
                rel_rest = rest[parent.name].inverted() @ rest[pb.name]
                basis = rel_rest.inverted() @ world[parent.name].inverted() @ m
            keys[pb.name].append((f, basis))
    scene.frame_set(saved_frame)
    if dst.animation_data and dst_action is not None:
        dst.animation_data.action = dst_action
    action = bpy.data.actions.new(src_action.name)
    action.use_fake_user = True
    for k in ("wildframe_frames", "wildframe_fps"):
        if src_action.get(k) is not None:
            action[k] = src_action[k]
    dst.animation_data_create()
    dst.animation_data.action = action
    for pb in order:
        prev = None
        for f, basis in keys[pb.name]:
            loc, rot, scl = basis.decompose()
            pb.location = loc
            pb.scale = scl
            if pb.rotation_mode == "QUATERNION":
                if prev is not None and prev.dot(rot) < 0:
                    rot.negate()  # keep quaternion keys on one hemisphere: no flips between frames
                pb.rotation_quaternion = rot
                prev = rot.copy()
                rpath = "rotation_quaternion"
            elif pb.rotation_mode == "AXIS_ANGLE":
                axis, angle = rot.to_axis_angle()
                pb.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
                rpath = "rotation_axis_angle"
            else:
                e = rot.to_euler(pb.rotation_mode, prev) if prev is not None else rot.to_euler(pb.rotation_mode)
                pb.rotation_euler = e
                prev = e.copy()
                rpath = "rotation_euler"
            for path in ("location", rpath, "scale"):
                pb.keyframe_insert(path, frame=f, group=pb.name)
    if object_root and len({tuple(round(v, 6) for row in m for v in row) for _, m in object_keys}) > 1:
        prev = None
        for f, m in object_keys:  # root motion: key the rig object
            loc, rot, scl = m.decompose()
            dst.location, dst.scale = loc, scl
            if dst.rotation_mode == "QUATERNION":
                dst.rotation_quaternion = rot
                rpath = "rotation_quaternion"
            else:
                e = rot.to_euler(dst.rotation_mode, prev) if prev is not None else rot.to_euler(dst.rotation_mode)
                dst.rotation_euler = e
                prev = e.copy()
                rpath = "rotation_euler"
            for path in ("location", rpath, "scale"):
                dst.keyframe_insert(path, frame=f, group="Object Transforms")
    for fc in _fcurves(action):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    return action, [pb.name for pb in order]


def _match_rotation_modes(action, rig):
    """Animations from Unreal key quaternions. A bone set to an Euler mode ignores those keys, so convert them to
    the bone's own Euler order (the user's rig settings stay untouched). Returns the converted bone names."""
    from mathutils import Quaternion
    quats = {}
    for fc in _fcurves(action):
        m = re.match(r'pose\.bones\["(.+)"\]\.rotation_quaternion$', fc.data_path)
        if m:
            quats.setdefault(m.group(1), {})[fc.array_index] = fc
    done = []
    for bone, chans in quats.items():
        pb = rig.pose.bones.get(bone)
        if pb is None or pb.rotation_mode in ("QUATERNION", "AXIS_ANGLE") or len(chans) != 4:
            continue
        frames = sorted({round(kp.co.x, 4) for fc in chans.values() for kp in fc.keyframe_points})
        eulers, prev = [], None
        for f in frames:
            q = Quaternion([chans[i].evaluate(f) for i in range(4)])
            e = q.to_euler(pb.rotation_mode, prev) if prev is not None else q.to_euler(pb.rotation_mode)
            eulers.append(e)
            prev = e
        path = 'pose.bones["%s"].rotation_euler' % bone
        curves = []
        for i in range(3):
            try:
                fc = action.fcurve_ensure_for_datablock(rig, path, index=i, group_name=bone)
            except (AttributeError, TypeError):
                fc = action.fcurves.find(path, index=i) or action.fcurves.new(path, index=i, action_group=bone)
            fc.keyframe_points.clear()
            fc.keyframe_points.add(len(frames))
            for k, (f, e) in enumerate(zip(frames, eulers)):
                fc.keyframe_points[k].co = (f, e[i])
                fc.keyframe_points[k].interpolation = "LINEAR"
            fc.update()
            curves.append(fc)
        for fc in chans.values():
            fc.keyframe_points.clear()
        done.append(bone)
    return done


def _rest_local(arm, name):
    bone = arm.data.bones.get(name)
    if bone is None:
        return None
    return (bone.parent.matrix_local.inverted() @ bone.matrix_local) if bone.parent else bone.matrix_local.copy()


def _rebase_action(action, src, dst):
    """Blender pose keys are relative to each bone's rest pose. Re-express the keys made for src's rest pose against
    dst's rest pose (same bone names), so the absolute animation is identical. Returns the adjusted bone names."""
    from mathutils import Matrix, Quaternion, Euler, Vector
    curves = {}
    for fc in _fcurves(action):
        m = re.match(r'pose\.bones\["(.+)"\]\.(location|rotation_quaternion|rotation_euler|scale)$', fc.data_path)
        if m:
            curves.setdefault(m.group(1), {})[(m.group(2), fc.array_index)] = fc
    adjusted = []
    for bone, chans in curves.items():
        rs, rt = _rest_local(src, bone), _rest_local(dst, bone)
        if rs is None or rt is None:
            continue
        delta = rt.inverted() @ rs
        if all(abs(delta[i][j] - (1.0 if i == j else 0.0)) < 1e-5 for i in range(4) for j in range(4)):
            continue
        frames = sorted({round(kp.co.x, 4) for fc in chans.values() for kp in fc.keyframe_points})
        quat = any(k[0] == "rotation_quaternion" for k in chans)
        values = []
        for f in frames:
            def ev(path, i, default):
                fc = chans.get((path, i))
                return fc.evaluate(f) if fc else default
            loc = Vector([ev("location", i, 0.0) for i in range(3)])
            rot = Quaternion([ev("rotation_quaternion", i, 1.0 if i == 0 else 0.0) for i in range(4)]) if quat \
                else Euler([ev("rotation_euler", i, 0.0) for i in range(3)]).to_quaternion()
            scl = Vector([ev("scale", i, 1.0) for i in range(3)])
            basis = delta @ Matrix.LocRotScale(loc, rot, scl)
            values.append(basis.decompose())
        for (path, i), fc in chans.items():
            fc.keyframe_points.clear()
        for path, count in (("location", 3), ("rotation_quaternion" if quat else "rotation_euler", 4 if quat else 3),
                            ("scale", 3)):
            for i in range(count):
                fc = chans.get((path, i))  # the FBX importer keys every channel; missing ones stay at rest
                if fc is None:
                    continue
                fc.keyframe_points.add(len(frames))
                for k, (f, (l, r, sc)) in enumerate(zip(frames, values)):
                    v = {"location": l, "scale": sc}.get(path)
                    if v is None:
                        v = r if quat else r.to_euler()
                    fc.keyframe_points[k].co = (f, v[i])
                    fc.keyframe_points[k].interpolation = "LINEAR"
                fc.update()
        adjusted.append(bone)
    return adjusted


def _action_range(action):
    """(first, last) frame to export: Unreal's exact frame count when the action came from Unreal, the action's
    manual frame range when set, otherwise its keyed range."""
    start = int(round(action.frame_range[0]))
    if action.get("wildframe_frames"):  # Unreal counts frames as intervals: N frames = N + 1 keys
        return start, start + int(action["wildframe_frames"])
    if getattr(action, "use_frame_range", False):
        return int(action.frame_start), int(action.frame_end)
    return start, int(round(action.frame_range[1]))


class _CentimetreRig:
    """Temporary centimetre copy of a rig (armature + its meshes + action) for export to Unreal.

    Unreal wants bone transforms in centimetres with no scale on the root bone. Blender stores metres, and every
    FBX unit option puts the x100 either on the root node (Unreal keeps it in animation tracks) or nowhere. So we
    export a scaled duplicate with the scene unit set to centimetres; the user's own objects are never touched."""

    def __init__(self, members, animated=False):
        self.members = members
        self.animated = animated
        self.copies = []
        self.saved_unit = None

    def __enter__(self):
        scene = bpy.context.scene
        arm = next(o for o in self.members if o.type == "ARMATURE")
        mapping = {}
        for o in self.members:
            c = o.copy()
            if o.data is not None:
                c.data = o.data.copy()
            scene.collection.objects.link(c)
            mapping[o] = c
            self.copies.append(c)
        for o, c in mapping.items():
            if o.parent in mapping:
                c.parent = mapping[o.parent]
                c.matrix_parent_inverse = o.matrix_parent_inverse.copy()
            for mod in getattr(c, "modifiers", []):
                if mod.type == "ARMATURE" and mod.object in mapping:
                    mod.object = mapping[mod.object]
        rig = mapping[arm]
        action = arm.animation_data.action if arm.animation_data else None
        if action is not None:
            rig.animation_data.action = None
        rig.matrix_world = arm.matrix_world.copy()
        rig.scale = rig.scale * 100.0
        bpy.context.view_layer.update()
        with ctx.object_mode(), ctx.view3d():
            ctx.select_only(self.copies)
            bpy.context.view_layer.objects.active = rig
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        for c in self.copies:  # skinning is exported as weights: never bake the current pose into the mesh
            for mod in getattr(c, "modifiers", []):
                if mod.type == "ARMATURE":
                    mod.show_viewport = False
                    mod.show_render = False
        if not self.animated:
            rig.data.pose_position = "REST"
            action = None
        if action is not None:
            act = action.copy()
            self.copies_action = act
            for fc in _fcurves(act):
                if fc.data_path.endswith(".location") or fc.data_path == "location":
                    for kp in fc.keyframe_points:
                        kp.co.y *= 100.0
                        kp.handle_left.y *= 100.0
                        kp.handle_right.y *= 100.0
                    fc.update()
            rig.animation_data.action = act
            slot = getattr(arm.animation_data, "action_slot", None)
            if slot is not None and getattr(act, "slots", None):
                try:
                    rig.animation_data.action_slot = act.slots[0]
                except Exception:  # noqa: BLE001
                    pass
        for key in ("wildframe_root_bone", "wildframe_unreal_skeleton"):
            if arm.get(key):
                rig[key] = arm[key]
        self.saved_unit = scene.unit_settings.scale_length
        scene.unit_settings.scale_length = 0.01
        self.rig = rig
        return [mapping[o] for o in self.members]

    def __exit__(self, *exc):
        bpy.context.scene.unit_settings.scale_length = self.saved_unit
        act = getattr(self, "copies_action", None)
        for c in self.copies:
            data = c.data
            bpy.data.objects.remove(c)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Armature):
                    bpy.data.armatures.remove(data)
        if act is not None and act.users == 0:
            bpy.data.actions.remove(act)
        return False


def _spawn_instances(base, item, collection):
    """Foliage / instanced meshes from Unreal: one shared mesh, one linked duplicate per instance."""
    sub = bpy.data.collections.new(_safe(item.get("name") or base.name) + "_Instances")
    collection.children.link(sub)
    local = base.matrix_world.copy()  # importer conversion (identity after the import scale is baked)
    names = []
    rows = item["instances"]
    prefix = _safe(item.get("name") or base.name)
    for i, r in enumerate(rows):
        inst = {"unrealLocationCm": r[0:3], "unrealAxes": [r[3:6], r[6:9], r[9:12]], "unrealScale": r[12:15]}
        obj = base if i == 0 else bpy.data.objects.new("%s_%04d" % (prefix, i), base.data)
        if i:
            sub.objects.link(obj)
        obj.matrix_world = _unreal_to_blender_matrix(inst) @ local
        names.append(obj.name)
    return names[1:]


def _family(root):
    out = [root]
    for child in root.children_recursive:
        out.append(child)
    return out


@command("BRIDGE.STATUS", "Show running Wildframe Forge apps on this computer (Unreal editors and Blender sessions), the "
         "exchange folder and the most recent transfer packages.")
def status(params):
    return {
        "unreal": [{"endpoint": r.get("endpoint"), "project": r.get("document") or r.get("project"),
                    "version": r.get("version"), "pid": r.get("pid")} for r in instances.list_instances("unreal")],
        "blender": [{"endpoint": r.get("endpoint"), "file": r.get("document"), "pid": r.get("pid")}
                    for r in instances.list_instances("blender")],
        "exchangeFolder": exchange.exchange_root(prefs.get().exchange_dir or None),
        "recentPackages": exchange.list_packages(prefs.get().exchange_dir or None, 8),
    }


@command("BRIDGE.SEND_TO_UNREAL",
         "Export objects (names, a collection, or the selection) and import them into the running Unreal editor as "
         "assets under 'destination'. Each top-level object becomes its own asset (combine=true makes one asset). "
         "Armatures go as skeletal meshes (or animation-only with animation_only=true). Works while both apps are open.",
         params={"names": {"type": "array"}, "collection": {"type": "string"},
                 "destination": {"type": "string", "default": "/Game/FromBlender"},
                 "format": {"type": "string", "enum": ["fbx", "glb"], "default": "fbx"},
                 "combine": {"type": "boolean", "default": False},
                 "asset_name": {"type": "string", "description": "Name when combine=true"},
                 "center_at_origin": {"type": "boolean", "default": True,
                                      "description": "Export each asset with its pivot at the world origin"},
                 "animation": {"type": "boolean", "default": False},
                 "animation_only": {"type": "boolean", "default": False},
                 "skeleton": {"type": "string", "description": "Existing Unreal skeleton for animation imports"},
                 "replace_existing": {"type": "boolean", "default": True},
                 "keep_duplicate_suffix": {"type": "boolean", "default": False,
                                           "description": "Keep Blender's .001 suffixes in asset and material names "
                                                          "(by default Pillar.001 is sent as Pillar when that "
                                                          "name is free in the send)"},
                 "nanite": {"type": "boolean", "default": False, "description": "Enable Nanite on the static meshes"},
                 "use_source_skeleton": {"type": "boolean", "default": True,
                                         "description": "A rig that came from Unreal is imported back onto its "
                                                        "original Skeleton asset (keeps all animations working)"},
                 "deform_bones_only": {"type": "boolean",
                                       "description": "Only bones marked Deform (default: true for meshes, so "
                                                      "control rigs stay in Blender; false for animations, so every "
                                                      "animated bone reaches Unreal)"},
                 "materials": {"type": "boolean", "default": True,
                               "description": "Rebuild materials in Unreal (textures, roughness, metallic, normal, "
                                              "emission, opacity) instead of plain grey slots"},
                 "bake_procedural": {"type": "boolean", "default": True,
                                     "description": "Bake inputs driven by procedural nodes (noise, ramps, bump, "
                                                    "non-Principled shaders) to textures with Cycles"},
                 "bake_size": {"type": "integer", "default": 1024, "enum": [256, 512, 1024, 2048, 4096]},
                 "place_in_level": {"type": "boolean", "default": False,
                                    "description": "Also spawn the imported meshes in the open Unreal level at "
                                                   "their Blender positions"},
                 "as_landscape": {"type": "boolean", "default": False,
                                  "description": "Send the selected meshes as Unreal Landscapes (terrain heights "
                                                 "sampled from above). Terrain that came from an Unreal Landscape "
                                                 "always goes back as a Landscape"},
                 "landscape_resolution": {"type": "integer", "default": 0,
                                          "description": "Landscape quads along the longest side (rounded to a "
                                                         "multiple of 63); 0 = match the mesh's own density"},
                 "unreal_project": {"type": "string", "description": "Pick an editor when several are open. When Unreal "
                                                                      "is closed: the project (name or .uproject path) "
                                                                      "the delivery waits for (default: the project "
                                                                      "Unreal last had open)"},
                 "import_into_unreal": {"type": "boolean", "default": True},
                 "queue_if_closed": {"type": "boolean", "default": True,
                                     "description": "If Unreal is closed, keep the package in the delivery mailbox; "
                                                    "Unreal imports it when the editor opens"}},
         mutating=False, long_running=True)
def send_to_unreal(params):
    objs = io_cmds.resolve_selection(dict(params, selected=True))
    folder = exchange.new_package_dir("blender", prefs.get().exchange_dir or None)
    scene_objs = [o for o in objs if o.type in ("LIGHT", "CAMERA")]
    terrain_objs = [o for o in objs if o.type in GEOMETRY_TYPES and o.type != "ARMATURE"
                    and (params["as_landscape"] or o.get("wildframe_landscape"))]
    objs = [o for o in objs if o.type not in ("LIGHT", "CAMERA") and o not in terrain_objs]
    groups, parent_of, renamed_from = [], {}, {}
    if objs and params["combine"]:
        groups = [(params.get("asset_name") or _safe(objs[0].name), objs)]
    elif objs:
        for r in _roots(objs):
            fam = [m for m in _family(r) if m.type not in ("LIGHT", "CAMERA")]
            if any(m.type == "ARMATURE" for m in fam):  # a rig travels as one skeletal mesh
                groups.append((_safe(r.name), fam))
                continue
            for m in fam:  # every object of a hierarchy is its own asset; Unreal re-attaches the actors
                if m.name.upper().startswith(COLLISION_PREFIXES) or m.type not in GEOMETRY_TYPES:
                    continue
                members = [m] + [c for c in m.children if c.name.upper().startswith(COLLISION_PREFIXES)]
                groups.append((_safe(m.name), members))
                if m.parent is not None and m.parent in fam and m.parent.type in GEOMETRY_TYPES:
                    parent_of[_safe(m.name)] = _safe(m.parent.name)
    if not params["combine"] and not params.get("keep_duplicate_suffix"):
        # Blender's duplicate suffix (Pillar.001) is not part of the asset's name: send it as "Pillar" unless
        # that would clash with another object in the same send
        rename = _strip_dup_suffixes([(g, members[0].name) for g, members in groups],
                                     {_safe(o.name) for o in bpy.data.objects} | {o.name for o in bpy.data.objects})
        if rename:
            renamed_from = {new: old for old, new in rename.items()}  # Unreal keeps updating an existing <old> asset
            groups = [(rename.get(g, g), members) for g, members in groups]
            parent_of = {rename.get(k, k): rename.get(v, v) for k, v in parent_of.items()}
    # LOD chains: <name>_LOD0 (or <name>) plus <name>_LOD1.. become one Unreal mesh with LODs
    lod_sets = {}
    if not params["combine"]:
        for gname, members in list(groups):
            m = re.match(r"^(.*?)_LOD(\d+)$", gname)
            if m and int(m.group(2)) > 0:
                lod_sets.setdefault(m.group(1), []).append((int(m.group(2)), members))
                groups.remove((gname, members))
        for gi, (gname, members) in enumerate(groups):
            base = re.sub(r"_LOD0$", "", gname)
            if base in lod_sets and base != gname:
                groups[gi] = (base, members)
    items, export_warnings, rig_for = [], [], {}
    for o in scene_objs:  # lights and cameras travel as values, not files
        item = scenexfer.describe(o)
        item.update(name=_safe(o.name), blenderLocationMeters=ctx.to_list(o.matrix_world.translation),
                    blenderMatrix=[ctx.to_list(row) for row in o.matrix_world])
        items.append(item)
    for o in terrain_objs:  # terrain becomes a real Landscape (heights only)
        try:
            item, w = terrainxfer.describe(o, folder, _safe(o.name), int(params.get("landscape_resolution") or 0))
            items.append(item)
            export_warnings.extend(w)
        except ValueError as error:
            export_warnings.append("%s not sent as a landscape: %s" % (o.name, error))
    for name, members in groups:
        root_objs = _roots(members)
        saved = {o.name: o.matrix_world.copy() for o in root_objs}
        world_positions = {o.name: ctx.to_list(o.matrix_world.translation) for o in root_objs}
        world_matrices = {o.name: [ctx.to_list(row) for row in o.matrix_world] for o in root_objs}
        centered = params["center_at_origin"] and not params["combine"]
        animated = params["animation"] or params["animation_only"]
        rig = next((o for o in members if o.type == "ARMATURE"), None)
        rig_action = rig.animation_data.action if (rig is not None and rig.animation_data) else None
        scene = bpy.context.scene
        saved_range = (scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base)
        if animated and rig_action is not None:
            scene.frame_start, scene.frame_end = _action_range(rig_action)
            if rig_action.get("wildframe_fps"):  # an animation from Unreal goes back at its own rate
                fps = float(rig_action["wildframe_fps"])
                scene.render.fps, scene.render.fps_base = int(round(fps)), round(fps) / fps
            if params["animation_only"] and not params.get("asset_name"):
                name = _safe(rig_action.name)
        try:
            if centered:
                from mathutils import Matrix
                for o in root_objs:
                    o.matrix_world = Matrix.Identity(4)
                bpy.context.view_layer.update()
            deform_only = params.get("deform_bones_only")
            if deform_only is None:
                # Blender rigs: deform bones only (control bones stay in Blender). Rigs that came from Unreal keep
                # every bone in animations (weapon/IK bones are keyed there too).
                deform_only = not (animated and rig is not None and rig.get("wildframe_root_bone"))
            fbx_opts = {"embed_textures": False, "path_mode": "AUTO",
                        "use_armature_deform_only": deform_only} if params["format"] == "fbx" else {}
            out_path = os.path.join(folder, "%s.%s" % (name, params["format"]))
            if rig is not None and params["format"] == "fbx":
                # rigs go through a temporary centimetre copy (see _CentimetreRig)
                fbx_opts["apply_scale_options"] = "FBX_SCALE_ALL"
                with _CentimetreRig(members, animated) as copies:
                    renamed = _armature_names_for_unreal(copies, export_warnings, deform_only)
                    try:
                        path = io_cmds.export_objects(copies, out_path, "fbx", fbx_opts, True, animated)
                    finally:
                        _restore_names(renamed)
                        scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base = saved_range
            else:
                try:
                    path = io_cmds.export_objects(members, out_path, params["format"], fbx_opts, True, animated)
                finally:
                    scene.frame_start, scene.frame_end, scene.render.fps, scene.render.fps_base = saved_range
        finally:
            if centered:
                for o in root_objs:
                    if o.name in saved:
                        o.matrix_world = saved[o.name]
                bpy.context.view_layer.update()
        kind = "animation" if params["animation_only"] else _kind(members, params["animation"])
        arms = [o for o in members if o.type == "ARMATURE"]
        if len(arms) == 1:
            rig_for[name] = arms[0].name
        item_skeleton = params.get("skeleton") or (arms[0].get("wildframe_unreal_skeleton") if len(arms) == 1 and
                                                    params["use_source_skeleton"] else None)
        mats = matxfer.describe_objects(members, folder, params["bake_procedural"], params["bake_size"]) \
            if (params["materials"] and kind != "animation") else []
        lods = []
        for index, lod_members in sorted(lod_sets.get(name, [])):
            lod_path = os.path.join(folder, "%s_LOD%d.%s" % (name, index, params["format"]))
            lod_saved = {o.name: o.matrix_world.copy() for o in _roots(lod_members)}
            try:
                from mathutils import Matrix
                for o in _roots(lod_members):
                    o.matrix_world = Matrix.Identity(4)
                bpy.context.view_layer.update()
                io_cmds.export_objects(lod_members, lod_path, params["format"],
                                       {"embed_textures": False, "path_mode": "AUTO"} if params["format"] == "fbx"
                                       else {}, True, False)
            finally:
                for o in _roots(lod_members):
                    o.matrix_world = lod_saved[o.name]
            lods.append({"file": os.path.basename(lod_path), "index": index})
        items.append({"file": os.path.basename(path), "name": name, "kind": kind, "format": params["format"],
                      "lods": lods,
                      "materials": mats, "skeleton": item_skeleton, "parent": parent_of.get(name),
                      "blenderLocationMeters": world_positions.get(root_objs[0].name) if root_objs else None,
                      "blenderMatrix": world_matrices.get(root_objs[0].name) if (root_objs and centered) else None})
        if name in renamed_from:
            items[-1]["renamedFrom"] = renamed_from[name]
    if not params.get("keep_duplicate_suffix"):  # same for material names (M_Stone.002 -> M_Stone); slots stay
        descs = [d for it in items for d in (it.get("materials") or []) if isinstance(d, dict) and d.get("name")]
        mat_rename = _strip_dup_suffixes([(d["name"], d["name"]) for d in descs], {m.name for m in bpy.data.materials})
        for d in descs:
            if d["name"] in mat_rename:
                d["renamedFrom"] = d["name"]
                d["name"] = mat_rename[d["name"]]
    manifest_path = exchange.write_manifest(folder, {
        "source": "blender", "target": "unreal", "units": "meters", "upAxis": "Z",
        "sourceFile": bpy.data.filepath, "destination": params["destination"], "items": items,
        "skeleton": params.get("skeleton"), "replaceExisting": params["replace_existing"],
    })
    result = {"package": folder, "manifest": manifest_path, "items": items}
    if export_warnings:
        result["_warnings"] = export_warnings
    if not params["import_into_unreal"]:
        result["_message"] = "Exported only. Import later with Unreal command BRIDGE.RECEIVE package=<folder>."
        return result
    unreal_params = {"package": folder, "placeInLevel": params["place_in_level"], "nanite": params["nanite"]}
    if params["queue_if_closed"] and not instances.list_instances("unreal"):
        # Unreal is closed (e.g. a PC that cannot run both): the package waits in the delivery mailbox and the
        # Unreal plugin imports it when the editor opens.
        # Addressed to the project the user named, else the project Unreal last had open, so it is not
        # imported into whichever project happens to open next.
        target = params.get("unreal_project") or exchange.last_seen("unreal")
        exchange.mark_delivery(folder, "waiting", options={k: v for k, v in unreal_params.items() if k != "package"},
                               for_document=target)
        exchange.ensure_hub()
        result["queued"] = True
        if target:
            result["forProject"] = target
            name = os.path.splitext(os.path.basename(str(target).replace("\\", "/")))[0]
            result["_message"] = ("Unreal is not open, so the package waits in the delivery mailbox for project %s. "
                                  "It is imported automatically the next time %s opens (other projects leave it "
                                  "alone). To send it to another project, pass unreal_project." % (name, name))
        else:
            result["_message"] = ("Unreal is not open, so the package waits in the delivery mailbox. Unreal imports "
                                  "it automatically the next time the editor opens with Wildframe Forge Bridge.")
        return result
    client = exchange.UnrealClient.find(params.get("unreal_project"))

    rig_names = {it["name"]: rig_for[it["name"]] for it in items if rig_for.get(it["name"])}

    def finish():
        reply = client.run("BRIDGE.RECEIVE", unreal_params)
        if not reply.get("ok"):
            raise CommandError(reply.get("code") or "UNREAL_IMPORT_FAILED",
                               reply.get("message") or "Unreal could not import the package.",
                               {"package": folder, "unreal": reply})
        data = reply.get("data") or {}
        learned = {}
        for entry in data.get("imported", []):
            skel = next((a["path"] for a in entry.get("assets", []) if a.get("class") == "Skeleton"), None)
            if skel and rig_names.get(entry.get("name")):
                learned[rig_names[entry["name"]]] = skel
        if learned:
            def remember():  # bpy only on the main thread
                for obj_name, skel in learned.items():
                    obj = bpy.data.objects.get(obj_name)
                    if obj is not None and not obj.get("wildframe_unreal_skeleton"):
                        obj["wildframe_unreal_skeleton"] = skel
                return None
            bpy.app.timers.register(remember, first_interval=0.0)
        return dict(result, unreal=data, unrealEndpoint=client.endpoint)

    result["_background"] = finish
    return result


@command("BRIDGE.RECEIVE", "Import an exchange package (folder or package.json) into Blender, e.g. one sent from "
         "Unreal with its BRIDGE.SEND_TO_BLENDER command. Without 'package', imports the newest package addressed "
         "to Blender.",
         params={"package": {"type": "string"}, "collection": {"type": "string", "default": "FromUnreal"},
                 "place_at_unreal_positions": {"type": "boolean", "default": True},
                 "materials": {"type": "boolean", "default": True,
                               "description": "Rebuild the sender's materials as Principled BSDF node setups"},
                 "replace_previous": {"type": "boolean", "default": True,
                                      "description": "Replace objects from an earlier send of the same asset"},
                 "target_armature": {"type": "string",
                                     "description": "Armature that receives animations (default: the rig in the "
                                                    "scene that came from the same Unreal skeleton)"},
                 "landscape_max_size": {"type": "integer", "default": 2017,
                                        "description": "Largest landscape grid (vertices per side) built at full "
                                                       "resolution; bigger ones are decimated"},
                 "apply_import_scale": {"type": "boolean", "default": True,
                                        "description": "Bake the importer's unit conversion into the mesh (scale 1)"}},
         mutating=True)
def receive(params):
    path = params.get("package")
    if not path:
        candidates = [p for p in exchange.list_packages(prefs.get().exchange_dir or None, 50) if p["target"] == "blender"]
        if not candidates:
            raise CommandError("NO_PACKAGE", "No exchange package addressed to Blender was found.")
        path = candidates[0]["folder"]
    manifest = exchange.read_manifest(path)
    render = bpy.context.scene.render
    scene_fps = (render.fps, render.fps_base)  # the FBX importer changes the scene fps to each file's
    anim_fps = None
    created, materials, warnings, row_x, animations = [], [], [], [0.0, None], []
    new_names, item_root, mat_cache = set(), {}, {}
    for item in manifest.get("items", []):
        if item.get("kind") in ("light", "camera"):
            coll = bpy.data.collections.get(params["collection"])
            if coll is None:
                coll = bpy.data.collections.new(params["collection"])
                bpy.context.scene.collection.children.link(coll)
            obj = scenexfer.build(item, coll)
            item_root[item.get("name")] = obj
            created.append(obj.name)
            continue
        if item.get("kind") == "landscape":
            coll = bpy.data.collections.get(params["collection"])
            if coll is None:
                coll = bpy.data.collections.new(params["collection"])
                bpy.context.scene.collection.children.link(coll)
            try:
                obj, step = terrainxfer.build(item, manifest["_folder"], coll, int(params["landscape_max_size"]))
            except ValueError as error:
                warnings.append("landscape %s: %s" % (item.get("name"), error))
                continue
            if step > 1:
                warnings.append("%s: landscape is %dx%d vertices, built at every %d. vertex (landscape_max_size)"
                                % (obj.name, item["sizeX"], item["sizeY"], step))
            item_root[item.get("name")] = obj
            created.append(obj.name)
            continue
        file_path = os.path.join(manifest["_folder"], item["file"])
        source_key = item.get("unrealAsset") and "%s|%s" % (item.get("unrealAsset"), item.get("name"))
        if source_key and params["replace_previous"] and item.get("kind") != "animation":
            # sending the same thing again updates it instead of piling up copies
            for old in [o for o in bpy.data.objects if o.get("wildframe_source") == source_key]:
                for child in list(old.children_recursive) + [old]:
                    if child.name in bpy.data.objects:
                        bpy.data.objects.remove(child)
        if item.get("kind") == "animation" and item.get("fps"):
            anim_fps = float(item["fps"])
        objs = io_cmds.import_file(file_path, item.get("format"))
        new_names.update(o.name for o in objs)
        coll = bpy.data.collections.get(params["collection"])
        if coll is None:
            coll = bpy.data.collections.new(params["collection"])
            bpy.context.scene.collection.children.link(coll)
        placement = _unreal_to_blender_matrix(item) if params["place_at_unreal_positions"] else None
        roots = _roots(objs)
        for obj in objs:
            for c in list(obj.users_collection):
                c.objects.unlink(obj)
            coll.objects.link(obj)
        bpy.context.view_layer.update()
        if item.get("materials") and params["materials"]:
            info = matxfer.apply_to_objects(objs, item["materials"], manifest["_folder"], mat_cache)
            warnings.extend(info["warnings"])
            materials.extend(info["materials"])
        if params["apply_import_scale"]:
            _normalize_rigs(objs, warnings)
            bpy.context.view_layer.update()
            roots = _roots(objs)
        if item.get("kind") == "animation":
            info = _apply_animation(objs, item, params, warnings)
            if info:
                animations.append(info)
            if info and info.get("appliedTo"):
                created.extend(o.name for o in objs)
                continue
        roots = _roots(objs)
        if params["apply_import_scale"]:
            # bake the importer's unit/axis conversion (e.g. 0.01 for centimetre FBX) into the mesh so objects
            # arrive with clean scale 1 (then the Unreal actor's own scale) and round-trip back at their real size
            from mathutils import Matrix
            for obj in roots:
                if obj.type == "MESH" and not obj.children and obj.data.users == 1:
                    obj.data.transform(obj.matrix_world)
                    obj.matrix_world = Matrix.Translation(obj.matrix_world.translation)
                    obj.data.update()
        if placement is None and roots and params["place_at_unreal_positions"] and not item.get("instances"):
            # assets sent without a level position: line them up along +X from the 3D cursor, no overlaps
            bpy.context.view_layer.update()
            from mathutils import Matrix, Vector
            width = _width(objs)
            if row_x[1] is None:  # first unplaced item: start 1 m past everything already in the scene
                row_x[1] = max([_max_x(o) for o in bpy.context.scene.objects if o.name not in new_names] or [0.0])
            start = Vector((row_x[1] + 1.0 + row_x[0] + width / 2.0, 0.0, 0.0))
            for obj in roots:
                obj.matrix_world = Matrix.Translation(start) @ obj.matrix_world
            row_x[0] += width + 0.5
        if placement is not None:
            bpy.context.view_layer.update()
            for obj in roots:
                # keep the importer's own unit/axis conversion, then place like the Unreal actor
                obj.matrix_world = placement @ obj.matrix_world
        if item.get("instances") and len(roots) == 1 and roots[0].type == "MESH":
            created.extend(_spawn_instances(roots[0], item, coll))
        if len(roots) == 1 and item.get("name"):
            roots[0].name = _safe(item["name"])
            item_root[item["name"]] = roots[0]
        if source_key:
            for obj in roots:
                obj["wildframe_source"] = source_key
        for obj in objs:
            if obj.type == "ARMATURE":
                if item.get("unrealSkeleton"):
                    obj["wildframe_unreal_skeleton"] = item["unrealSkeleton"]
                if item.get("unrealAsset"):
                    obj["wildframe_unreal_asset"] = item["unrealAsset"]
                for child in obj.children:
                    if child.type == "MESH" and re.match(r"^%s\.\d{3}$" % re.escape(obj.name), child.name):
                        child.name = obj.name + "_Mesh"
        created.extend(o.name for o in objs)
    # rebuild Unreal actor attachments as Blender parenting
    by_item = item_root
    group_empties = {}
    for item in manifest.get("items", []):  # parts of one Unreal actor (Blueprint components) share an empty
        child, group = by_item.get(item.get("name")), item.get("group")
        if child is None or not group:
            continue
        empty = group_empties.get(group)
        if empty is None:
            empty = bpy.data.objects.new(_safe(group), None)
            empty.empty_display_type = "PLAIN_AXES"
            for c in child.users_collection:
                c.objects.link(empty)
            empty.matrix_world = child.matrix_world.copy()
            empty.matrix_world.normalize()
            group_empties[group] = empty
            created.append(empty.name)
        world = child.matrix_world.copy()
        child.parent = empty
        child.matrix_world = world
    for item in manifest.get("items", []):
        child, parent = by_item.get(item.get("name")), by_item.get(item.get("parent") or "")
        if child is not None and parent is not None and child is not parent:
            world = child.matrix_world.copy()
            child.parent = parent
            child.matrix_world = world
    if anim_fps:  # animations play at their Unreal rate; otherwise the scene keeps its own fps
        render.fps = int(round(anim_fps))
        render.fps_base = round(anim_fps) / anim_fps
    else:
        render.fps, render.fps_base = scene_fps
    out = {"package": manifest["_folder"], "source": manifest.get("source"), "created": created,
           "materials": list(dict.fromkeys(materials))}
    if animations:
        out["animations"] = animations
    if warnings:
        out["_warnings"] = warnings[:20]
    return out


@command("BRIDGE.UNREAL_COMMAND", "Run any Wildframe Forge Unreal command from Blender (e.g. to check what exists before "
         "sending). Waits up to timeout_sec.",
         params={"command": {"type": "string"}, "params": {"type": "object", "default": {}},
                 "unreal_project": {"type": "string"}, "timeout_sec": {"type": "number", "default": 120}},
         required=["command"], long_running=True)
def unreal_command(params):
    client = exchange.UnrealClient.find(params.get("unreal_project"))

    def finish():
        return client.run(params["command"], params["params"], params["timeout_sec"])

    return {"_background": finish}
