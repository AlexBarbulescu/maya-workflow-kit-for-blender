# SPDX-License-Identifier: GPL-3.0-or-later
"""tnt: drag a Shelf Editor button to a new place in Shelf Contents.

Blender runs operator buttons on mouse release, so a press-and-hold drag on a list row can't start a modal.
Instead the grip handle works like Blender's grab: click it, the button follows the mouse up/down one row at a
time, click (or Enter) to drop, right-click / Esc to put it back.
"""

import bpy

from .shelf_editor_draft import _draft_buttons, _load_button, _redraw, _set_message, _wm

ROW_PX = 20  # UIList DEFAULT row height in pixels at UI scale 1 (UI_UNIT_Y)


class ALLSET_OT_shelf_editor_drag_button(bpy.types.Operator):
    bl_idname = "allset.shelf_editor_drag_button"
    bl_label = "Drag Button"
    bl_description = ("Move this button: move the mouse up/down, click to drop it there. "
                      "Right-click or Esc puts it back")
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        wm = _wm(context)
        self.buttons = _draft_buttons(wm.allset_se_shelf)
        self.start = wm.allset_se_index
        if not self.buttons or not 0 <= self.start < len(self.buttons):
            return {'CANCELLED'}
        self.original = list(self.buttons)
        self.start_y = event.mouse_y
        self.row_px = ROW_PX * context.preferences.system.ui_scale
        self.current = self.start
        _set_message(context, "Move the mouse to place the button, click to drop (Esc cancels)")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _place(self, context, target):
        button = self.original[self.start]
        order = self.original[:self.start] + self.original[self.start + 1:]
        order.insert(target, button)
        self.buttons[:] = order  # in place: the draft holds this same list
        self.current = target
        _load_button(context, target)
        _redraw(context)

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            steps = round((self.start_y - event.mouse_y) / self.row_px)  # mouse down = later row
            target = max(0, min(len(self.original) - 1, self.start + steps))
            if target != self.current:
                self._place(context, target)
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'SPACE'}:
            _set_message(context, "")
            return {'FINISHED'}
        if event.value == 'PRESS' and event.type in {'RIGHTMOUSE', 'ESC'}:
            self._place(context, self.start)
            _set_message(context, "")
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


def draw_grip(layout):
    layout.operator(ALLSET_OT_shelf_editor_drag_button.bl_idname, text="", icon='GRIP')
