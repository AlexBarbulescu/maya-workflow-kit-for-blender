"""Native Undo/Redo restores shading/deletion inputs and displaced shading modifiers."""
from importlib import import_module
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(__file__))
from sim import MODULE, check, ev, run, setup, step, view3d, win

C = {}


def mod(name):
    return import_module(MODULE+'.'+name)


def viewport():
    area, region = view3d()
    return bpy.context.temp_override(window=win(), area=area, region=region)


def ob():
    return bpy.data.objects[C['object']]


def digest():
    ex = mod('operators.extrude')
    return ex.coords_hash(bmesh.from_edit_mesh(ob().data)) if ob().mode == 'EDIT' else ex.mesh_coords_hash(ob().data)


def undo():
    ev('Z', 'PRESS', ctrl=True)
    ev('Z', 'RELEASE', ctrl=True)


def redo():
    ev('Z', 'PRESS', shift=True)
    ev('Z', 'RELEASE', shift=True)


@step
def initialize():
    setup()
    mod('preferences').get().model_history_files = True
    wm = bpy.context.window_manager
    check('clean startup registers shading and deletion channels',
          hasattr(wm.allset_history, 'angle_text') and hasattr(wm.allset_history, 'enabled_text'))
    with viewport():
        C['object'] = bpy.context.object.name
        bpy.ops.ed.undo_push(message='Start shape history')
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.ed.undo_push(message='Before component soften')
        C['before'] = digest()
        bpy.ops.allset.soften_harden('EXEC_DEFAULT', True, angle=180)
        C['soft'] = digest()
        check('first edit-mode soften creates its input', len(mod('operators.model_history').records(ob())) == 1)
    undo()


@step
def undo_shading():
    with viewport():
        check('Undo first soften restores geometry and removes its recipe',
              digest() == C['before'] and mod('operators.model_history').read(ob()) is None)
        check('Undo soften stays in component mode', ob().mode == 'EDIT')
    redo()


@step
def redo_shading_and_delete():
    with viewport():
        check('Redo soften restores geometry and input',
              digest() == C['soft'] and len(mod('operators.model_history').records(ob())) == 1)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.allset.delete_components('EXEC_DEFAULT', True)
        check('deleting all faces records an empty result', len(bmesh.from_edit_mesh(ob().data).verts) == 0
              and len(mod('operators.model_history').records(ob())) == 2)
    undo()


@step
def undo_deletion():
    with viewport():
        check('Undo deletion restores faces and earlier shading input',
              digest() == C['soft'] and len(mod('operators.model_history').records(ob())) == 1)
    redo()


@step
def redo_deletion_and_edit():
    with viewport():
        check('Redo deletion restores empty mesh and both inputs', len(bmesh.from_edit_mesh(ob().data).verts) == 0
              and len(mod('operators.model_history').records(ob())) == 2)
        node = mod('ui.node_attributes').target(bpy.context)
        mod('ui.node_attributes').apply(bpy.context, node, {'enabled': False})
        check('attribute UI can bypass empty deletion', len(bmesh.from_edit_mesh(ob().data).faces) == 6)
    undo()


@step
def undo_attribute_edit():
    with viewport():
        data = mod('operators.model_history').read(ob())
        check('one Undo restores deletion parameter and empty result', len(bmesh.from_edit_mesh(ob().data).verts) == 0
              and data['nodes'][-1]['params']['enabled'])
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.mesh.primitive_cube_add()
        C['object'] = bpy.context.object.name
        bpy.ops.object.shade_auto_smooth('EXEC_DEFAULT', True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.context.tool_settings.mesh_select_mode = (False, True, False)
        bm = bmesh.from_edit_mesh(ob().data)
        mod('operators.extrude').deselect_all(bm)
        next(iter(bm.edges)).select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob().data)
        bpy.ops.ed.undo_push(message='Before shading modifier bake')
        C['modifier_before'] = digest()
        check('modifier setup has Smooth by Angle', bool(mod('operators.menu_items').smooth_by_angle_mods(ob())))
        bpy.ops.allset.soften_harden('EXEC_DEFAULT', True, angle=180)
        C['modifier_after'] = digest()
        check('component soften removes conflicting modifier and records its input',
              not mod('operators.menu_items').smooth_by_angle_mods(ob())
              and len(mod('operators.model_history').records(ob())) == 1)
    undo()


@step
def undo_modifier_bake():
    with viewport():
        check('one Undo restores modifier geometry and pre-history state',
              digest() == C['modifier_before'] and bool(mod('operators.menu_items').smooth_by_angle_mods(ob()))
              and mod('operators.model_history').read(ob()) is None)
        check('Undo modifier bake returns to component mode', ob().mode == 'EDIT')
    redo()


@step
def redo_modifier_bake():
    with viewport():
        check('one Redo restores modifier bake and recorded input',
              digest() == C['modifier_after'] and not mod('operators.menu_items').smooth_by_angle_mods(ob())
              and len(mod('operators.model_history').records(ob())) == 1 and ob().mode == 'EDIT')


@step
def native_move_then_input_edit():
    with viewport():
        bpy.ops.transform.translate('EXEC_DEFAULT', True, value=(.2, 0, 0))
        C['moved'] = digest()
        check('native movement keeps INPUTS visible', mod('ui.in_view').cb_record(bpy.context, ob()) is not None)
        node = mod('ui.node_attributes').target(bpy.context)
        mod('ui.node_attributes').apply(bpy.context, node, dict(node.params, angle=0))
        C['edited_move'] = digest()
        check('editing old input captures native movement as a tweak',
              [item['kind'] for item in mod('operators.model_history').read(ob())['nodes']] == ['SOFT_EDGE', 'TWEAK'])
    undo()


@step
def undo_reconciled_move():
    with viewport():
        check('Undo input edit preserves the preceding native move', digest() == C['moved'])
        check('Undo reconciliation removes its tweak but retains the old input',
              len(mod('operators.model_history').read(ob())['nodes']) == 1
              and mod('ui.in_view').cb_record(bpy.context, ob()) is not None)
    redo()


@step
def redo_reconciled_move():
    with viewport():
        check('Redo restores the input edit and tweak geometry', digest() == C['edited_move'])
        check('Redo restores both editable inputs', len(mod('operators.model_history').read(ob())['nodes']) == 2)


run()
