# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-operation settings for the remaining Modeling-menu commands with native Blender options."""

import bpy

from .option_windows_spec import F, Window, _components, _op
from ..ui import menu_map


class NativeField(F):
    """Keep Blender's property limits, angle display and enum labels in the existing option editor."""

    def __init__(self, prop):
        self.rna = prop
        kind = {'BOOLEAN': 'bool', 'INT': 'int', 'FLOAT': 'float', 'ENUM': 'enum'}[prop.type]
        default = tuple(prop.default_array) if getattr(prop, 'is_array', False) else prop.default
        items = [item.identifier for item in prop.enum_items] if kind == 'enum' else None
        super().__init__(prop.identifier, prop.name + ':', 'vec3' if getattr(prop, 'is_array', False) else kind,
                         default, items=items)

    def prop(self):
        p = self.rna
        kwargs = dict(name=p.name, description=p.description, default=self.default)
        if p.type == 'BOOLEAN':
            return bpy.props.BoolProperty(**kwargs)
        if p.type == 'ENUM':
            return bpy.props.EnumProperty(**kwargs, items=[(e.identifier, e.name, e.description)
                                                          for e in p.enum_items])
        kwargs.update(min=p.hard_min, max=p.hard_max)
        if p.type == 'INT':
            return bpy.props.IntProperty(**kwargs)
        kwargs.update(subtype=p.subtype, unit=p.unit)
        if p.is_array:
            return bpy.props.FloatVectorProperty(**kwargs, size=p.array_length)
        return bpy.props.FloatProperty(**kwargs)


def _run(context, path, values, action=None):
    _, target, fixed = action or menu_map.spec(path)
    kwargs = {**fixed, **values}
    if target == 'outliner.orphans_purge':
        bpy.data.orphans_purge(**kwargs)
        return {'FINISHED'}
    from ..ui.status_line import main_view3d
    area, region = main_view3d(context.window.screen if context.window else None)
    if area is None:
        raise RuntimeError('Open a 3D View to apply these settings.')
    with context.temp_override(area=area, region=region):
        if path == 'Select/Similar' and context.mode == 'EDIT_MESH':
            return bpy.ops.allset.component_command('EXEC_DEFAULT', item=path)
        if target == 'allset.snap_together':
            result = bpy.ops.allset.snap_together('INVOKE_DEFAULT', **kwargs)
            return {'FINISHED'} if result & {'FINISHED', 'RUNNING_MODAL'} else result
        if target.startswith(('mesh.', 'uv.')):
            return _components(context, target, 'FACE', **kwargs)
        if target == 'curve.cyclic_toggle' and context.mode == 'OBJECT':
            curves = [ob for ob in context.selected_objects if ob.type in {'CURVE', 'SURFACE'}]
            if not curves:
                raise RuntimeError('Select a curve or surface first.')
            if context.view_layer.objects.active not in curves:
                context.view_layer.objects.active = curves[0]
            bpy.ops.object.mode_set(mode='EDIT')
            try:
                bpy.ops.curve.select_all(action='SELECT')
                return _op(target, **kwargs)
            finally:
                bpy.ops.object.mode_set(mode='OBJECT')
        return _op(target, **kwargs)


def _native(key, path, names, native_target=None):
    _, target, fixed = menu_map.spec(path)
    action = ('v3d', native_target, {}) if native_target else None
    module, op = (native_target or target).split('.')
    rna = getattr(getattr(bpy.ops, module), op).get_rna_type()
    fields = [NativeField(rna.properties[name]) for name in names if name in rna.properties]
    label = path.rsplit('/', 1)[-1]
    return Window('tnt_' + key, label + ' Options', label, (target, fixed), fields,
                  lambda c, v: _run(c, path, v, action), paths=(path,),
                  missing=tuple(name for name in names if name not in rna.properties),
                  enabled=(lambda v, name: bpy.context.mode == 'OBJECT') if path == 'Select/Similar' else None)


WINDOWS = [
    _native('optimize_scene', 'File/Optimize Scene Size', ('do_local_ids', 'do_linked_ids', 'do_recursive')),
    _native('select_similar', 'Select/Similar', ('extend',)),
    Window('tnt_align_objects', 'Align Objects Options', 'Align Objects', ('allset.align_objects', {}), [
        F('mode', 'Align mode:', 'enum', 'MID', items=['MIN', 'MID', 'MAX']),
        F('axis_x', 'Axes:', 'bool', True, text='X'),
        F('axis_y', '', 'bool', False, text='Y'), F('axis_z', '', 'bool', False, text='Z')],
        lambda c, v: _run(c, 'Modify/Snap Align Objects/Align Objects', v),
        paths=('Modify/Snap Align Objects/Align Objects',)),
    Window('tnt_snap_together', 'Snap Together Tool Options', 'Enter Tool', ('allset.snap_together', {}), [
        F('set_orientation', 'Set orientation:', 'bool', True)],
        lambda c, v: _run(c, 'Modify/Snap Together Tool', v), paths=('Modify/Snap Together Tool',)),
    _native('nurbs_to_polygons', 'Modify/Convert/NURBS to Polygons', ('keep_original', 'merge_customdata')),
    _native('edges_to_curve', 'Modify/Convert/Polygon Edges to Curve', ('keep_original',)),
    _native('retopologize', 'Mesh/Retopologize', ('mode', 'target_ratio', 'target_edge_length', 'target_faces',
            'use_mesh_symmetry', 'use_preserve_sharp', 'use_preserve_boundary', 'preserve_attributes',
            'smooth_normals', 'seed')),
    _native('unsmooth', 'Mesh/Unsmooth', ('iterations',)),
    _native('quadrangulate', 'Mesh/Quadrangulate', ('face_threshold', 'shape_threshold', 'topology_influence',
            'uvs', 'vcols', 'seam', 'sharp', 'materials', 'deselect_joined')),
    _native('curve_open_close', 'Curves/Open/Close', ('direction',)),
    _native('surface_open_close', 'Surfaces/Open/Close', ('direction',)),
    _native('remove_blend_shape', 'Deform/Blend Shape#2/Remove', ('all', 'apply_mix')),
    _native('mirror_deformer_weights', 'Deform/Mirror Deformer Weights',
            ('mirror_weights', 'flip_group_names', 'all_groups', 'use_topology')),
    _native('camera_uv', 'UV/Camera-based', ('orthographic', 'camera_bounds', 'correct_aspect',
            'clip_to_bounds', 'scale_to_bounds')),
    # Keep the native controls and saved presets while unsaved clicks use Maya's round projection.
    _native('cylinder_uv', 'UV/Cylindrical', ('direction', 'align', 'pole', 'seam', 'radius', 'correct_aspect',
            'clip_to_bounds', 'scale_to_bounds'), native_target='uv.cylinder_project'),
    _native('sphere_uv', 'UV/Spherical', ('direction', 'align', 'pole', 'seam', 'correct_aspect',
            'clip_to_bounds', 'scale_to_bounds'), native_target='uv.sphere_project'),
    _native('create_groom', 'Generate/Create Interactive Groom Splines', ('align', 'location', 'rotation')),
    Window('tnt_insert_knot', 'Insert Knot Options', 'Insert Knot', ('allset.curve_insert_knot', {}), [
        F('location', 'Insert location:', 'enum', 'AT', items=['AT', 'BETWEEN']),
        F('mode', 'Multiplicity:', 'enum', 'INCREASE', items=['INCREASE', 'SET']),
        F('number', 'Number:', 'int', 1, lo=1, hi=100),
        F('keep_original', 'Keep original:', 'bool', False)],
        lambda c, v: _run(c, 'Curves/Insert Knot', v), paths=('Curves/Insert Knot',)),
    Window('tnt_offset_curve', 'Offset Curve Options', 'Offset Curve', ('allset.offset_curve', {}), [
        F('distance', 'Offset distance:', 'float', 1.0)],
        lambda c, v: _run(c, 'Curves/Offset/Offset Curve', v), paths=('Curves/Offset/Offset Curve',)),
]


INTERFACE_ACTIONS = {'wm.call_panel', 'allset.open_editor'}
TOOL_OPTIONS = {'transform.shrink_fatten': 'builtin.shrink_fatten'}


def open_tool_options(context, target):
    from ..ui.status_line import main_view3d
    area, region = main_view3d(context.window.screen if context.window else None)
    if area is None:
        return {'CANCELLED'}
    with context.temp_override(area=area, region=region):
        result = bpy.ops.allset.menu_tool(tool=TOOL_OPTIONS[target], edit=True)
        if 'FINISHED' in result:
            return bpy.ops.allset.editor_toggle(editor='TOOL_SETTINGS', show=True)
        return result


def option_kind(target, fixed, rna):
    if target in TOOL_OPTIONS:
        return 'tool'
    if target in INTERFACE_ACTIONS:
        return 'dialog'
    # Selector and context-routing properties are not settings of the chosen command.
    shown = [p for p in rna.properties if p.identifier not in {'rna_type', 'module', 'cycle'}
             and p.identifier not in fixed and not p.is_hidden and p.type not in {'POINTER', 'COLLECTION'}]
    return 'redo' if shown else 'generic'
