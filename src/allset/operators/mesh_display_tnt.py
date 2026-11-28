# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh Display commands that need a selection, viewport, or a live submenu."""

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import color_sets_maya
from .option_windows_spec import _components


REVERSE_SCOPES = (
    ('FACES', "Selected faces", ""),
    ('EXTRACT', "Selected faces, then extract", "Split the reversed faces off inside the same mesh"),
    ('SHELL', "All faces in the shell", "Reverse all visible faces connected to the selection by edges"),
)
_previous_shading = {}


def show_colors(space):
    shading = space.shading
    if (shading.type, shading.color_type) != ('SOLID', 'VERTEX'):
        _previous_shading[space.as_pointer()] = (shading.type, shading.color_type)
        shading.type, shading.color_type = 'SOLID', 'VERTEX'


class ALLSET_OT_toggle_mesh_colors(bpy.types.Operator):
    """Toggle color attributes in the viewport and restore the previous shading when switched off"""
    bl_idname = "allset.toggle_mesh_colors"
    bl_label = "Toggle Display Colors Attribute"

    def execute(self, context):
        from ..ui.status_line_buttons import view3d_space

        space = view3d_space(context)
        if space is None:
            self.report({'WARNING'}, "No 3D View to show colors in.")
            return {'CANCELLED'}
        shading = space.shading
        if (shading.type, shading.color_type) == ('SOLID', 'VERTEX'):
            shading.type, shading.color_type = _previous_shading.pop(space.as_pointer(), ('SOLID', 'MATERIAL'))
        else:
            show_colors(space)
        return {'FINISHED'}


class ALLSET_OT_paint_mesh_colors(bpy.types.Operator):
    """Enter Blender Vertex Paint on the active mesh and paint its current color set"""
    bl_idname = "allset.paint_mesh_colors"
    bl_label = "Paint Vertex Color Tool"

    option_box: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        result = self.execute(context)
        if self.option_box and 'FINISHED' in result:
            _viewport_action(context, "VIEW3D_PT_tools_brush_settings")
        return result

    def execute(self, context):
        from ..ui.status_line_buttons import view3d_space

        ob = context.active_object
        if ob is None or ob.type != 'MESH' or context.mode not in {'OBJECT', 'EDIT_MESH', 'PAINT_VERTEX'}:
            self.report({'WARNING'}, "Select a mesh to paint.")
            return {'CANCELLED'}
        if not ob.data.is_editable:
            self.report({'WARNING'}, "The mesh data is read-only.")
            return {'CANCELLED'}
        edit = context.mode == 'EDIT_MESH'
        if edit:
            bpy.ops.object.mode_set(mode='OBJECT')
        if context.mode == 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='VERTEX_PAINT')
            finally:
                if edit and context.mode == 'OBJECT':
                    bpy.ops.object.mode_set(mode='EDIT')
        if context.mode != 'PAINT_VERTEX':
            return {'CANCELLED'}
        space = view3d_space(context)
        if space is not None:
            show_colors(space)
        return {'FINISHED'}


class ALLSET_OT_create_empty_color_set(bpy.types.Operator):
    """Make an empty current color set on each selected mesh"""
    bl_idname = "allset.create_empty_color_set"
    bl_label = "Create Empty Color Set"
    bl_options = {'UNDO'}

    name: StringProperty(name="Name", default=color_sets_maya.NEW_SET, options={'SKIP_SAVE'})
    data_type: EnumProperty(name="Color Range", items=[
        ('FLOAT_COLOR', "Unclamped", "Full precision color"),
        ('BYTE_COLOR', "Clamped", "8-bit color in the 0–1 range")],
        default='FLOAT_COLOR', options={'SKIP_SAVE'})
    domain: EnumProperty(name="Store On", items=[
        ('CORNER', "Face Corners", "Store a separate color per vertex per face"),
        ('POINT', "Vertices", "Share color across faces meeting at a vertex")],
        default='CORNER', options={'SKIP_SAVE'})

    def execute(self, context):
        if context.mode not in {'OBJECT', 'EDIT_MESH'}:
            return {'CANCELLED'}
        meshes = [ob.data for ob in color_sets_maya._meshes(context)]
        if not meshes or not self.name.strip():
            self.report({'WARNING'}, "Select an editable mesh and enter a color set name.")
            return {'CANCELLED'}
        edit = context.mode == 'EDIT_MESH'
        if edit:
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            for me in meshes:
                first = not len(me.color_attributes)
                color_sets_maya.new_set(me, self.name.strip(), self.data_type, self.domain)
                if first:
                    me.color_attributes.render_color_index = me.color_attributes.active_color_index
                me.update()
        finally:
            if edit:
                bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


def _viewport_action(context, panel=None):
    from ..ui.status_line_buttons import main_view3d

    area = context.area
    if area and area.type == 'VIEW_3D':
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    else:
        area, region = main_view3d(context.screen)
    if region is None:
        return {'CANCELLED'}
    with context.temp_override(area=area, region=region):
        if panel is not None:
            if getattr(bpy.types, panel).poll(context):
                return bpy.ops.wm.call_panel('INVOKE_DEFAULT', name=panel, keep_open=True)
            return {'CANCELLED'}
        return bpy.ops.transform.rotate_normal('INVOKE_DEFAULT')


class ALLSET_OT_edit_vertex_normals(bpy.types.Operator):
    """Rotate the selected normals in Edit Mode. The option box opens the normals display controls"""
    bl_idname = "allset.edit_vertex_normals"
    bl_label = "Vertex Normal Edit Tool"

    option_box: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        if context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, "Select mesh components in Edit Mode to edit their normals.")
            return {'CANCELLED'}
        panel = "VIEW3D_PT_overlay_edit_mesh_normals" if self.option_box else None
        return _viewport_action(context, panel)


def _shell_faces(seed):
    seen = set(seed)
    pending = list(seen)
    while pending:
        face = pending.pop()
        for edge in face.edges:
            for other in edge.link_faces:
                if other not in seen and not other.hide:
                    seen.add(other)
                    pending.append(other)
    return seen


def _conform_faces(faces):
    """Find the minority winding of each manifold group, without changing any faces yet."""
    unseen = set(faces)
    flip = set()
    for seed in faces:
        if seed not in unseen:
            continue
        unseen.remove(seed)
        groups = ([seed], [])
        pending = [(seed, False)]
        while pending:
            face, reversed_ = pending.pop()
            for edge in face.edges:
                neighbors = edge.link_faces
                if len(neighbors) != 2:
                    continue
                other = neighbors[1] if neighbors[0] == face else neighbors[0]
                if other not in unseen:
                    continue
                unseen.remove(other)
                direction = reversed_ ^ (not edge.is_contiguous)
                groups[direction].append(other)
                pending.append((other, direction))
        keep, change = groups
        flip.update(change if len(change) <= len(keep) else keep)
    return flip


class ALLSET_OT_reverse_mesh_normals(bpy.types.Operator):
    """Reverse face winding or conform selected faces to the majority winding in each shell"""
    bl_idname = "allset.reverse_mesh_normals"
    bl_label = "Reverse Normals"
    bl_options = {'UNDO'}

    scope: EnumProperty(items=(*REVERSE_SCOPES, ('CONFORM', "Conform", "")), default='FACES', options={'SKIP_SAVE'})
    preserve_user_normals: BoolProperty(name="Preserve User Normals Direction", options={'SKIP_SAVE'})

    def execute(self, context):
        if context.mode == 'OBJECT':
            scope = 'FACES' if self.scope == 'EXTRACT' else self.scope
            return _components(context, "allset.reverse_mesh_normals", 'FACE', scope=scope,
                               preserve_user_normals=self.preserve_user_normals)
        if context.mode != 'EDIT_MESH':
            return {'CANCELLED'}
        meshes = [o.data for o in context.objects_in_mode_unique_data if o.type == 'MESH']
        selected = {mesh: [f for f in bmesh.from_edit_mesh(mesh).faces if f.select and not f.hide] for mesh in meshes}
        if not any(selected.values()):
            self.report({'WARNING'}, "Select faces first.")
            return {'CANCELLED'}
        if self.scope == 'EXTRACT' and not context.tool_settings.mesh_select_mode[2]:
            self.report({'WARNING'}, "Switch to face selection to reverse and extract faces.")
            return {'CANCELLED'}

        command = {'CONFORM': _conform_faces, 'SHELL': _shell_faces}.get(self.scope)
        targets = {mesh: command(faces) for mesh, faces in selected.items()} if command else selected
        if not any(targets.values()):
            return {'CANCELLED'}
        custom = [me for me, faces in targets.items() if faces and self._has_user_normals(me)]
        saved_normals = {}
        face_ids = {}
        if custom:
            from . import normals_reverse_tnt

            for me in targets:
                bmesh.from_edit_mesh(me).faces.index_update()
            face_ids = {me: {face.index for face in faces} for me, faces in targets.items()}
            saved_normals = normals_reverse_tnt.snapshot(custom)
            targets = {me: [f for f in bmesh.from_edit_mesh(me).faces if f.index in indices]
                       for me, indices in face_ids.items()}

        result = self._flip_targets(targets) if command else bpy.ops.mesh.flip_normals()
        if 'FINISHED' in result:
            if saved_normals:
                normals_reverse_tnt.restore(saved_normals, face_ids, self.preserve_user_normals)
            if self.scope == 'EXTRACT':
                bpy.ops.mesh.split()
        return result

    @staticmethod
    def _has_user_normals(mesh):
        if mesh.has_custom_normals:
            return True
        bm = bmesh.from_edit_mesh(mesh)
        return any(seq.layers.float_vector.get("custom_normal") is not None
                   for seq in (bm.verts, bm.faces, bm.loops))

    @staticmethod
    def _flip_targets(targets):
        saved = {}
        try:
            for mesh, faces in targets.items():
                bm = bmesh.from_edit_mesh(mesh)
                flags = [(el, el.select) for seq in (bm.faces, bm.edges, bm.verts) for el in seq]
                saved[mesh] = (flags, list(bm.select_history))
                for face in bm.faces:
                    face.select_set(face in faces)
            return bpy.ops.mesh.flip_normals()
        finally:
            for mesh, (flags, history) in saved.items():
                for elem, selected in flags:
                    if elem.select != selected:
                        elem.select_set(selected)
                bm = bmesh.from_edit_mesh(mesh)
                bm.select_history.clear()
                for elem in history:
                    bm.select_history.add(elem)
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)


class ALLSET_MT_vertex_bake_sets(bpy.types.Menu):
    """Assign selected meshes to a vertex bake set in this scene"""
    bl_idname = "ALLSET_MT_vertex_bake_sets"
    bl_label = "Assign Existing Set"

    def draw(self, context):
        self.layout.operator_context = 'EXEC_DEFAULT'
        names = sorted(color_sets_maya.bake_sets(context.scene))
        if not names:
            row = self.layout.row()
            row.enabled = False
            row.label(text="No bakesets defined")
        for name in names:
            self.layout.operator("allset.bake_set_assign", text=name, translate=False).name = name


classes = (ALLSET_OT_toggle_mesh_colors, ALLSET_OT_paint_mesh_colors, ALLSET_OT_create_empty_color_set,
           ALLSET_OT_edit_vertex_normals, ALLSET_OT_reverse_mesh_normals,
           ALLSET_MT_vertex_bake_sets)
