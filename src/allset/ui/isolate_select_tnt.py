# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit the object membership of a single viewport's Isolate Select."""

import bpy
from bpy.props import EnumProperty

from ..operators.dag import hierarchy
from .panel_cameras import _space
from .panel_menu_data import ISOLATE


class ALLSET_OT_isolate_members(bpy.types.Operator):
    """Edit which objects and descendants are shown in this isolated viewport"""
    bl_idname = "allset.isolate_members"
    bl_label = "Edit Isolate Select"
    bl_options = {'INTERNAL'}

    action: EnumProperty(items=(('LOAD', "Load", "Replace the isolated subset"),
                                ('ADD', "Add", "Add to the isolated subset"),
                                ('REMOVE', "Remove", "Remove from the isolated subset")),
                         options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        space = _space(context)
        return space is not None and space.local_view is not None and context.mode == 'OBJECT'

    def execute(self, context):
        layer = context.view_layer
        objects = {ob for ob in layer.objects if ob is not None}
        # The Outliner can select objects outside this viewport's local view.
        selected = [ob for ob in objects if ob.select_get(view_layer=layer)]
        if not selected:
            self.report({'WARNING'}, "Select objects in the viewport or Outliner first")
            return {'CANCELLED'}
        members = objects.intersection(hierarchy(selected))
        space = context.space_data
        if self.action == 'LOAD':
            for ob in objects:
                ob.local_view_set(space, ob in members)
        else:
            for ob in members:
                ob.local_view_set(space, self.action == 'ADD')
        return {'FINISHED'}


class ALLSET_MT_panel_isolate(bpy.types.Menu):
    """Isolate this viewport or edit which objects it shows"""
    bl_idname = "ALLSET_MT_panel_isolate"
    bl_label = "Isolate Select"

    def draw(self, context):
        from .panel_menus import draw_rows

        layout = self.layout
        draw_rows(layout, context, ISOLATE[:1])
        layout.separator()
        layout.operator_context = 'EXEC_REGION_WIN'
        for _kind, label, idname, props in ISOLATE[1:]:
            layout.operator(idname, text=label).action = props['action']
