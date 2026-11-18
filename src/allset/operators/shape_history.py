# SPDX-License-Identifier: GPL-3.0-or-later
"""Shading and component-deletion inputs using the existing modeling recipe engine."""

import math

import bpy

from .. import undo_steps
from . import extrude, extrude_rebuild, model_history, prim_history, soften_harden_edges, units


def recording(context):
    return model_history.enabled() and prim_history.history_on(context)


def _soften(bm, params, unit):
    from . import menu_items
    angle = float(params['angle'])
    if not math.isfinite(angle) or not 0 <= angle <= 180:
        raise ValueError('The edge angle must be between 0 and 180 degrees')
    bm.normal_update()
    menu_items.soften_harden(bm, angle, soften_harden_edges._picked(bm, params['whole']),
                            params.get('texture_borders', False))  # tnt
    if params['whole']:
        extrude.deselect_all(bm)
    return list(bm.verts)


SOFT_EDGE = extrude.add_spec(extrude.Spec(
    'SOFT_EDGE', 'polySoftEdge', ('angle',), {'angle': 'Angle'}, {'angle': 30.0},
    {'angle': 'NONE'}, None, 'shape_history_edit', _soften, hidden=('whole', 'texture_borders'),
    in_view=False, preserve_ids=True))


def _delete_builder(mode):
    def build(bm, params, unit):
        from . import component
        if params['enabled']:
            component.delete_components(bm, mode)
        extrude.deselect_all(bm)
        bm.normal_update()
        return list(bm.verts)
    return build


def _tweak(bm, params, unit):
    from . import history_references as references
    handles = references.layers(bm)
    vertices = {}
    for vertex in bm.verts:
        key = references.identity(vertex, handles)
        if key in vertices:
            raise ValueError('Vertex adjustments have ambiguous component identities')
        vertices[key] = vertex
    for high, low, x, y, z in params['deltas']:
        vertex = vertices.get((high, low))
        if vertex is None:
            raise ValueError('A vertex used by the recorded adjustments no longer exists')
        if not all(math.isfinite(value) for value in (x, y, z)):
            raise ValueError('Vertex adjustments must be finite')
        vertex.co = tuple(float(value)+delta for value, delta in zip(vertex.co, (x, y, z)))
    bm.normal_update()
    return list(bm.verts)


TWEAK = extrude.add_spec(extrude.Spec(
    'TWEAK', 'polyTweak', (), {}, {}, {}, None, 'shape_history_edit', _tweak,
    hidden=('deltas',), in_view=False, preserve_ids=True, allow_empty=True))


DELETE = {mode: extrude.add_spec(extrude.Spec(
    'DELETE_'+mode, 'polyDelEdge' if mode == 'EDGE' else 'deleteComponent',
    ('enabled',), {'enabled': 'Enabled'}, {'enabled': True}, {'enabled': 'BOOL'},
    None, 'shape_history_edit', _delete_builder(mode), in_view=False,
    preserve_ids=True, allow_empty=True)) for mode in ('FACE', 'EDGE', 'VERT')}


def soften(context, ob, bm, angle, whole=False, texture_borders=False):
    """Record after the command has baked any displaced Smooth by Angle modifiers."""
    if whole:
        for sequence in (bm.verts, bm.edges, bm.faces):
            for element in sequence:
                element.select = True
    record = extrude.record_new if ob.mode == 'EDIT' else extrude_rebuild._record_bm
    return record(context, ob, bm, SOFT_EDGE,
                  {'angle': angle, 'whole': whole, 'texture_borders': texture_borders}, units.maya_unit(context.scene))


@undo_steps.no_redo_panel
class ALLSET_OT_shape_history_edit(bpy.types.Operator):
    """Edit the last shading or component-deletion input"""
    bl_idname = 'allset.shape_history_edit'
    bl_label = 'Edit Shape History'
    bl_options = {'REGISTER', 'UNDO'}

    angle: bpy.props.FloatProperty(name='Angle', default=30.0, min=0.0, max=180.0, options={'SKIP_SAVE'})
    enabled: bpy.props.BoolProperty(name='Enabled', default=True, options={'SKIP_SAVE'})
    whole: bpy.props.BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'}

    def execute(self, context):
        def params(spec):
            return {name: getattr(self, name) for name in spec.fields}
        if context.mode == 'OBJECT':
            ob = context.active_object
            rec = extrude.object_record(ob)
            ok = (rec is not None and rec.spec.edit_op == 'shape_history_edit'
                  and extrude_rebuild.run_object(ob, rec, dict(rec.params, **params(rec.spec)), units.maya_unit(context.scene)))
            return {'FINISHED'} if ok else {'CANCELLED'}
        done = 0
        for ob in context.objects_in_mode_unique_data:
            rec = extrude.current(ob)
            if rec is not None and rec.spec.edit_op == 'shape_history_edit':
                values = dict(rec.params, **params(rec.spec))
                done += bool(extrude.run(ob, rec, values, units.maya_unit(context.scene)))
        return {'FINISHED'} if done else {'CANCELLED'}


classes = (ALLSET_OT_shape_history_edit,)
