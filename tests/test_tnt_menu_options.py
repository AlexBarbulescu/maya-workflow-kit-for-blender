"""Remaining Modeling option boxes open settings before changing the scene."""
from importlib import import_module

import bpy

import kit

menus = import_module(kit.MODULE + '.ui.menu_map')
boxes = import_module(kit.MODULE + '.ui.menu_option_box')
options = import_module(kit.MODULE + '.operators.option_windows')
tnt = import_module(kit.MODULE + '.operators.option_windows_menu_tnt')


def test_new_windows_and_native_fields_are_registered_without_scene_changes():
    before = [(ob.name, ob.data, ob.matrix_world.copy()) for ob in bpy.context.scene.objects]
    assert len(tnt.WINDOWS) == 19
    assert len({window.key for window in tnt.WINDOWS}) == 19
    for window in tnt.WINDOWS:
        for path in window.paths:
            assert options.find_path(path) is window, path
            assert boxes.option_kind(path) == 'window', path
        assert hasattr(bpy.ops.allset, window.idname.split('.')[1])
        for field in window.fields:
            field.prop()
    assert before == [(ob.name, ob.data, ob.matrix_world.copy()) for ob in bpy.context.scene.objects]


def test_selector_boxes_and_tool_options_do_not_use_redo():
    for path in ('Create/Lights/Point Light', 'Mesh/Booleans/Union', 'Display/Heads Up Display/Poly Count',
                 'Generate/Interactive Grooming Tools/Comb Brush', 'Curves/Extend/Extend Curve'):
        assert boxes.option_kind(path) == 'generic', path
    assert boxes.option_kind('Modify/Transformation Tools/Move Normal Tool') == 'tool'
    assert boxes.option_kind('Display/Polygons/Custom Polygon Display') == 'dialog'
    align = options.find_path('Modify/Snap Align Objects/Align Objects').defaults()
    assert (align['axis_x'], align['axis_y'], align['axis_z']) == (True, False, False)


def test_cylindrical_options_apply_to_whole_object_and_restore_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    for ob in bpy.context.view_layer.objects:
        ob.select_set(ob == cube)
    for layer in list(cube.data.uv_layers):
        cube.data.uv_layers.remove(layer)
    window = options.find_path('UV/Cylindrical')
    assert options.run(window, bpy.context, window.defaults()) == {'FINISHED'}
    assert bpy.context.mode == 'OBJECT' and bpy.context.active_object == cube
    assert len(cube.data.uv_layers) == 1
