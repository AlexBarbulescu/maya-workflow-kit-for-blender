# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya Mesh Display normal commands: Set Vertex Normal, Lock / Unlock Normals, Average, Set to Face.

Maya rules on explicit meshes.

Object selections affect all corners. Vertex and edge selections use their vertices, and face selections use
only their own corners. Blender's split normals store directions relative to the local smooth fan.
"""

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty, FloatVectorProperty
from mathutils import Vector
from mathutils.kdtree import KDTree

from .. import results, undo_steps
from . import units

AVERAGE_DISTANCE = 0.1      # Average Normals Options default distance
SET_NORMAL = (1.0, 0.0, 0.0)  # Maya Set Vertex Normal Options default value (X / Y / Z)


# --- pure rules (no bpy) ---------------------------------------------------------------------------------------

def unit(v):
    v = Vector(v)
    return tuple(v.normalized()) if v.length > 1e-12 else (0.0, 0.0, 0.0)


def set_vertex_normal(normals, locked, corners, xyz):
    """Maya Set Vertex Normal (polyNormalPerVertex -xyz): the corners get the unit ``xyz`` and are locked."""
    n = unit(xyz)
    for c in corners:
        normals[c] = n
        locked[c] = True


def distance_groups(positions, distance):
    """Group vertices within the world-space distance, including vertices from different meshes."""
    if not positions:
        return []
    parent = list(range(len(positions)))
    tree = KDTree(len(positions))
    for v, position in enumerate(positions):
        tree.insert(position, v)
    tree.balance()

    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    for a, position in enumerate(positions):
        for _co, b, _distance in tree.find_range(position, distance + 1e-9):
            if a < b:
                parent[find(a)] = find(b)
    groups = {}
    for v in range(len(positions)):
        groups.setdefault(find(v), []).append(v)
    return groups.values()


# --- Blender mesh access ----------------------------------------------------------------------------------------

def locked_corners(me):
    """Per corner: has a custom (locked) normal."""
    attr = me.attributes.get("custom_normal")
    if attr is None or not me.has_custom_normals:
        return [False] * len(me.loops)
    if attr.data_type == 'INT16_2D':
        return [tuple(d.value) != (0, 0) for d in attr.data]
    flags = [d.vector.length_squared > 0.0 for d in attr.data]
    if attr.domain == 'POINT':
        return [flags[loop.vertex_index] for loop in me.loops]
    if attr.domain == 'FACE':
        return [flags[p.index] for p in me.polygons for _ in p.loop_indices]
    return flags


def current(me):
    return [tuple(n.vector) for n in me.corner_normals], locked_corners(me)


def computed(me):
    """The corner normals Blender computes for ``me`` without custom normals."""
    plain = me.copy()
    try:
        attr = plain.attributes.get("custom_normal")
        if attr is not None:
            plain.attributes.remove(attr)
        return [tuple(n.vector) for n in plain.corner_normals]
    finally:
        bpy.data.meshes.remove(plain)


def write(me, normals, locked):
    """Write the locked directions and restore automatic calculation on the other corners."""
    attr = me.attributes.get("custom_normal")
    if not any(locked):
        if attr is not None:
            me.attributes.remove(attr)
        return
    if attr is not None and attr.data_type == 'FLOAT_VECTOR':
        if all(locked):
            if attr.domain != 'CORNER':
                me.attributes.remove(attr)
                attr = me.attributes.new("custom_normal", 'FLOAT_VECTOR', 'CORNER')
            attr.data.foreach_set("vector", [axis for normal in normals for axis in normal])
            me.update()
            return
        me.attributes.remove(attr)
    auto = computed(me)
    me.normals_split_custom_set([normals[i] if locked[i] else auto[i] for i in range(len(me.loops))])
    for entry, lock in zip(me.attributes["custom_normal"].data, locked):
        if not lock:
            entry.value = (0, 0)
        elif tuple(entry.value) == (0, 0):
            # Blender ignores the second angle when the first is zero, so this preserves the lock without tilting it.
            entry.value = (0, 1)
    me.update()


def _targets(context):
    if context.mode == 'EDIT_MESH':
        return [o for o in context.objects_in_mode_unique_data if o.type == 'MESH' and o.data.is_editable]
    if context.mode == 'OBJECT':
        return list({o.data: o for o in context.selected_objects if o.type == 'MESH' and o.data.is_editable}.values())
    return []


class _Selection:
    """Selected vertices / faces read in Edit Mode, then Object Mode for the custom-normal writes (Mesh API)."""

    def __init__(self, context):
        self.edit = context.mode == 'EDIT_MESH'
        self.face_mode = self.edit and context.tool_settings.mesh_select_mode[2]
        self.obs = _targets(context)
        self.sel = {}
        for ob in self.obs:
            if self.edit:
                bm = bmesh.from_edit_mesh(ob.data)
                bm.verts.index_update()  # tnt: indices may be dirty after editing topology
                bm.faces.index_update()
                self.sel[ob.name] = ({v.index for v in bm.verts if v.select and not v.hide},
                                     {f.index for f in bm.faces if f.select and not f.hide})
            else:
                me = ob.data
                self.sel[ob.name] = (set(range(len(me.vertices))), set(range(len(me.polygons))))
        if self.edit:
            bpy.ops.object.mode_set(mode='OBJECT')

    def close(self):
        if self.edit:
            bpy.ops.object.mode_set(mode='EDIT')

    def items(self):
        for ob in self.obs:
            verts, faces = self.sel[ob.name]
            yield ob, verts, faces


def corners_of_verts(me, verts, faces=None):
    out = {}
    if faces is None:
        for li, loop in enumerate(me.loops):
            if loop.vertex_index in verts:
                out.setdefault(loop.vertex_index, []).append(li)
    else:
        for fi in faces:
            for li in me.polygons[fi].loop_indices:
                out.setdefault(me.loops[li].vertex_index, []).append(li)
    return out


def _empty_warning(op, what):
    op.report({'WARNING'}, f"Select {what} (or a mesh in Object Mode).")
    return {'CANCELLED'}


@undo_steps.no_redo_panel
class ALLSET_OT_set_vertex_normal(bpy.types.Operator):
    """Set the normal of the selected vertices to a direction and lock it (Maya Mesh Display > Set Vertex Normal)"""
    bl_idname = "allset.set_vertex_normal"
    bl_label = "Set Vertex Normal"
    bl_options = {'REGISTER', 'UNDO'}

    x: FloatProperty(name="X", default=SET_NORMAL[0], options={'SKIP_SAVE'})
    y: FloatProperty(name="Y", default=SET_NORMAL[1], options={'SKIP_SAVE'})
    z: FloatProperty(name="Z", default=SET_NORMAL[2], options={'SKIP_SAVE'})

    def execute(self, context):
        if Vector((self.x, self.y, self.z)).length < 1e-12:
            self.report({'WARNING'}, "The normal can't be zero.")
            return {'CANCELLED'}
        sel = _Selection(context)
        done = 0
        try:
            for ob, verts, faces in sel.items():
                me = ob.data
                chosen = corners_of_verts(me, verts, faces if sel.face_mode else None)
                corners = [c for group in chosen.values() for c in group]
                if not corners:
                    continue
                normals, locked = current(me)
                set_vertex_normal(normals, locked, corners, (self.x, self.y, self.z))
                write(me, normals, locked)
                done += 1
        finally:
            sel.close()
        if not done:
            return _empty_warning(self, "vertices")
        results.result(self, f"polyNormalPerVertex -xyz {self.x:g} {self.y:g} {self.z:g}")
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_lock_normals(bpy.types.Operator):
    """Lock (freeze) the normals of the selected vertices (Maya Mesh Display > Lock Normals / Unlock Normals)"""
    bl_idname = "allset.lock_normals"
    bl_label = "Lock Normals"
    bl_options = {'REGISTER', 'UNDO'}

    unlock: BoolProperty(name="Unlock", default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        sel = _Selection(context)
        done = 0
        try:
            for ob, verts, faces in sel.items():
                me = ob.data
                chosen = corners_of_verts(me, verts, faces if sel.face_mode else None)
                corners = [c for group in chosen.values() for c in group]
                if not corners:
                    continue
                normals, locked = current(me)
                for c in corners:
                    locked[c] = not self.unlock
                write(me, normals, locked)
                done += 1
        finally:
            sel.close()
        if not done:
            return _empty_warning(self, "vertices")
        results.result(self, "polyNormalPerVertex -ufn true" if self.unlock else "polyNormalPerVertex -fn true")
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_average_normals(bpy.types.Operator):
    """Average the normals of the selected vertices, joining vertices closer than the distance (Maya Mesh Display >
    Average)"""
    bl_idname = "allset.average_normals"
    bl_label = "Average Normals"
    bl_options = {'REGISTER', 'UNDO'}

    distance: FloatProperty(name="Distance", default=AVERAGE_DISTANCE, min=0.0, options={'SKIP_SAVE'})
    replacement: FloatVectorProperty(name="Replace Zero Normals By", size=3, default=SET_NORMAL,
                                      options={'SKIP_SAVE'})

    def execute(self, context):
        sel = _Selection(context)
        try:
            from .normals_average_tnt import average_selection
            distance = self.distance * units.maya_unit(context.scene)
            done = average_selection(sel, distance, self.replacement)
        finally:
            sel.close()
        if not done:
            return _empty_warning(self, "vertices")
        results.result(self, f"polyAverageNormal -distance {self.distance:g}")
        return {'FINISHED'}


@undo_steps.no_redo_panel
class ALLSET_OT_set_to_face_normal(bpy.types.Operator):
    """Give the selected faces their face normal at every corner (Maya Mesh Display > Set to Face)"""
    bl_idname = "allset.set_to_face_normal"
    bl_label = "Set to Face Normals"
    bl_options = {'REGISTER', 'UNDO'}

    user_normal: BoolProperty(name="Set user normal", default=False, options={'SKIP_SAVE'},
                              description="Lock the face normals (Maya -setUserNormal); off = hard edges, unlocked")

    def execute(self, context):
        from .normals_set_to_face_tnt import set_to_face, target_corners  # tnt: Maya vertex-faces
        face_mode = context.mode != 'EDIT_MESH' or context.tool_settings.mesh_select_mode[2]
        sel = _Selection(context)
        done = 0
        try:
            for ob, verts, faces in sel.items():
                targets = target_corners(ob.data, verts, faces, face_mode)
                if targets:
                    set_to_face(ob.data, targets, self.user_normal)
                    done += 1
        finally:
            sel.close()
        if not done:
            return _empty_warning(self, "faces or vertices")
        results.result(self, "polySetToFaceNormal -setUserNormal" if self.user_normal else "polySetToFaceNormal")
        return {'FINISHED'}


classes = (ALLSET_OT_set_vertex_normal, ALLSET_OT_lock_normals, ALLSET_OT_average_normals,
           ALLSET_OT_set_to_face_normal)
