# SPDX-License-Identifier: GPL-3.0-or-later
"""tnt: drag a Shelf Editor button to a new place in Shelf Contents.

Press and hold the grip of the selected row, move the mouse up/down (the button follows one row at a time),
release to drop. Esc while holding puts it back.

Operator buttons only run on mouse release, so the grip is a toggle *property* instead: Blender starts its
drag-toggle on press-and-move, the property's update starts the modal while the mouse is still held, and the
modal ends on LEFTMOUSE RELEASE. Every event is passed through so Blender's own drag-toggle handler also ends.
"""

import bpy
from bpy.props import BoolProperty

from .shelf_editor_draft import _draft_buttons, _load_button, _redraw, _set_message, _wm

ROW_PX = 20  # UIList DEFAULT row height in pixels at UI scale 1 (UI_UNIT_Y)
_state = {"busy": False}


class ALLSET_OT_shelf_editor_drag_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_drag_button"
    bl_label = "Drag Button"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        wm = _wm(context)
        self.buttons = _draft_buttons(wm.allset_se_shelf)
        self.start = wm.allset_se_index
        # A plain click (released without moving) reaches us as the release itself: nothing to drag.
        if (event.type == 'LEFTMOUSE' and event.value == 'RELEASE') or not self.buttons \
                or not 0 <= self.start < len(self.buttons):
            return {'CANCELLED'}
        self.original = list(self.buttons)
        self.start_y = event.mouse_y
        self.row_px = ROW_PX * context.preferences.system.ui_scale
        self.current = self.start
        _state["busy"] = True
        _set_message(context, "Release to drop the button here (Esc puts it back)")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _place(self, context, target):
        order = self.original[:self.start] + self.original[self.start + 1:]
        order.insert(target, self.original[self.start])
        self.buttons[:] = order  # in place: the draft holds this same list
        self.current = target
        _load_button(context, target)
        _redraw(context)

    def _end(self, context):
        _state["busy"] = False
        _set_message(context, "")

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            steps = round((self.start_y - event.mouse_y) / self.row_px)  # mouse down = later row
            target = max(0, min(len(self.original) - 1, self.start + steps))
            if target != self.current:
                self._place(context, target)
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._end(context)
            return {'FINISHED', 'PASS_THROUGH'}
        elif event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._place(context, self.start)
            self._end(context)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}


def _grip_update(wm, context):
    if not wm.allset_se_grip:
        return
    wm.allset_se_grip = False  # stays off; it is only a trigger
    if not _state["busy"]:
        bpy.ops.allset.shelf_editor_drag_button('INVOKE_DEFAULT')


def draw_grip(layout, selected):
    # One shared trigger property can't tell rows apart, so only the selected row gets a live grip.
    if selected:
        layout.prop(bpy.context.window_manager, "allset_se_grip", text="", icon='GRIP', toggle=True)
    else:
        layout.label(text="", icon='BLANK1')


def register():
    bpy.types.WindowManager.allset_se_grip = BoolProperty(
        name="Drag Button",
        description="Press and hold, move the mouse up/down, release to drop the button there",
        options={'SKIP_SAVE'}, update=_grip_update)


def unregister():
    _state["busy"] = False
    if hasattr(bpy.types.WindowManager, "allset_se_grip"):
        del bpy.types.WindowManager.allset_se_grip
