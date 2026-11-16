"""tnt: options for a user shelf's Python button (Maya's doubleClickCommand).

A Python action may carry ``"options": [[label, code], ...]``. Double-click or Ctrl+click on that button pops up
the labels (the record's own text, so no kit strings); picking one runs its code like the button's own code
(``shelf_run.run_script``). Buttons without options keep the upstream behaviour. Hooked from ``shelf_run``
(Python branch) and ``shelf`` (class list) with one ``# tnt:`` line each.
"""
import bpy
from bpy.props import IntProperty, StringProperty


def popup(context, shelf, index, title, options):
    def draw(menu, _context):
        for i, (label, _code) in enumerate(options):
            op = menu.layout.operator(ALLSET_OT_shelf_python_option.bl_idname, text=label, translate=False)
            op.shelf, op.index, op.option = shelf, index, i

    context.window_manager.popup_menu(draw, title=title)
    return {'FINISHED'}


class ALLSET_OT_shelf_python_option(bpy.types.Operator):
    """Run this option of the shelf button"""
    bl_idname = "allset.shelf_python_option"
    bl_label = "Shelf Button Option"
    bl_options = {'INTERNAL', 'UNDO'}

    shelf: StringProperty()
    index: IntProperty()
    option: IntProperty()

    def execute(self, context):
        from .shelf_run import button_record, run_script
        b = button_record(self.shelf, self.index) or {}
        options = (b.get("action") or {}).get("options") or []
        if not 0 <= self.option < len(options):
            return {'CANCELLED'}
        label, code = options[self.option]
        ok, msg = run_script(context, f"{b.get('label', 'Shelf Button')} {label}", code)
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        return {'FINISHED'}
