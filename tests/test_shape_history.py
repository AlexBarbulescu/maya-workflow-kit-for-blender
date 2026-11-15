"""Persistent shading/deletion inputs preserve bindings and never overwrite unrecorded edits."""
from importlib import import_module
from copy import deepcopy
import json
import os
from pathlib import Path

import bmesh
import bpy
import kit

ex = import_module(kit.MODULE+'.operators.extrude')
history = import_module(kit.MODULE+'.operators.model_history')
refs = import_module(kit.MODULE+'.operators.history_references')
shapes = import_module(kit.MODULE+'.operators.shape_history')
menu = import_module(kit.MODULE+'.operators.menu_items')
nodes = import_module(kit.MODULE+'.ui.node_attributes')


def cube(edit=True):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    import_module(kit.MODULE+'.preferences').get().model_history_files = True
    bpy.context.window_manager.allset_construction_history = True
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.mesh.primitive_cube_add()
    ob = bpy.context.object
    if edit:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    return ob


def pick_face(ob):
    bm = bmesh.from_edit_mesh(ob.data)
    ex.deselect_all(bm)
    max(bm.faces, key=lambda face: face.calc_center_median().z).select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data)


def digest(ob):
    return (ex.coords_hash(bmesh.from_edit_mesh(ob.data)) if ob.mode == 'EDIT'
            else ex.mesh_coords_hash(ob.data))


def identities(bm):
    handles = refs.layers(bm)
    return {tuple(vertex.co): refs.identity(vertex, handles) for vertex in bm.verts}


def test_shading_between_extrusions_replays_and_preserves_existing_identities():
    ob = cube()
    pick_face(ob)
    assert bpy.ops.allset.extrude(thickness=.5) == {'FINISHED'}
    before_ids = identities(bmesh.from_edit_mesh(ob.data))
    assert bpy.ops.allset.soften_harden(angle=180) == {'FINISHED'}
    assert identities(bmesh.from_edit_mesh(ob.data)) == before_ids
    pick_face(ob)
    assert bpy.ops.allset.extrude(thickness=.25) == {'FINISHED'}
    data = history.read(ob)
    assert [node['kind'] for node in data['nodes']] == ['FACE', 'SOFT_EDGE', 'FACE']
    before = digest(ob)
    history.edit(ob, data['nodes'][0]['id'], dict(data['nodes'][0]['params'], thickness=1.0))
    assert digest(ob) != before
    assert len(history.read(ob)['nodes']) == 3 and ex.current(ob) is not None


def test_repeated_shading_commands_are_distinct_editable_inputs():
    ob = cube(edit=False)
    bpy.ops.allset.soften_harden(angle=180)
    bpy.ops.allset.soften_harden(angle=0)
    data = history.read(ob)
    assert len(data['nodes']) == 2
    assert len({node['name'] for node in data['nodes']}) == 2
    assert all(data['nodes'][0]['selection'][field] is None for field in ('vertices', 'edges', 'faces'))
    history.edit(ob, data['nodes'][0]['id'], {'angle': 90, 'whole': True})
    assert all(edge.use_edge_sharp for edge in ob.data.edges)
    assert ex.object_record(ob) is not None
    assert hasattr(bpy.context.window_manager.allset_history, 'angle_text')


def test_deletion_replays_after_an_earlier_extrusion():
    ob = cube()
    pick_face(ob)
    bpy.ops.allset.extrude(thickness=.5)
    pick_face(ob)
    assert bpy.ops.allset.delete_components() == {'FINISHED'}
    data = history.read(ob)
    assert [node['kind'] for node in data['nodes']] == ['FACE', 'DELETE_FACE']
    before = digest(ob)
    count = len(bmesh.from_edit_mesh(ob.data).faces)
    history.edit(ob, data['nodes'][0]['id'], dict(data['nodes'][0]['params'], thickness=1))
    assert digest(ob) != before and len(bmesh.from_edit_mesh(ob.data).faces) == count


def test_delete_every_face_can_be_disabled_and_reenabled_through_node_ui():
    ob = cube()
    assert bpy.ops.allset.delete_components() == {'FINISHED'}
    assert len(bmesh.from_edit_mesh(ob.data).verts) == 0
    node = nodes.target(bpy.context)
    assert node.spec is shapes.DELETE['FACE']
    node.commit(bpy.context, {'enabled': False})
    node.finish()
    assert len(bmesh.from_edit_mesh(ob.data).faces) == 6
    node.commit(bpy.context, {'enabled': True})
    node.finish()
    assert len(bmesh.from_edit_mesh(ob.data).verts) == 0
    data = history.read(ob)
    history.edit(ob, data['nodes'][0]['id'], {'enabled': False})
    assert len(bmesh.from_edit_mesh(ob.data).faces) == 6


def test_edge_and_vertex_deletion_keep_surviving_identities():
    for mode, index in (('EDGE', 1), ('VERT', 0)):
        ob = cube()
        bpy.context.tool_settings.mesh_select_mode = (mode == 'VERT', mode == 'EDGE', False)
        bm = bmesh.from_edit_mesh(ob.data)
        ex.deselect_all(bm)
        seq = bm.edges if mode == 'EDGE' else bm.verts
        seq.ensure_lookup_table()
        seq[index].select_set(True)
        bm.select_flush_mode()
        before = identities(bm)
        assert bpy.ops.allset.delete_components() == {'FINISHED'}
        after = identities(bmesh.from_edit_mesh(ob.data))
        assert after and len(after) < len(before)
        assert all(before[co] == identity for co, identity in after.items())
        data = history.read(ob)
        assert data['nodes'][-1]['kind'] == 'DELETE_'+mode
        history.edit(ob, data['nodes'][-1]['id'], {'enabled': False})
        assert len(bmesh.from_edit_mesh(ob.data).faces) == 6


def test_empty_selection_and_border_edges_do_not_add_nodes():
    ob = cube()
    pick_face(ob)
    bpy.ops.allset.delete_components()
    before = ob.data[history.KEY]
    assert bpy.ops.allset.delete_components() == {'CANCELLED'}
    bpy.context.tool_settings.mesh_select_mode = (False, True, False)
    bm = bmesh.from_edit_mesh(ob.data)
    next(edge for edge in bm.edges if len(edge.link_faces) == 1).select_set(True)
    bm.select_flush_mode()
    assert bpy.ops.allset.delete_components() == {'CANCELLED'}
    assert ob.data[history.KEY] == before


def test_direct_replay_refuses_unrecorded_geometry_and_shading_edits():
    for edit_mode in (False, True):
        ob = cube(edit=edit_mode)
        bpy.ops.allset.soften_harden(angle=180)
        data = history.read(ob)
        if edit_mode:
            bm = bmesh.from_edit_mesh(ob.data)
            next(iter(bm.edges)).smooth = False
            bmesh.update_edit_mesh(ob.data)
        else:
            ob.data.vertices[0].co.x += .2
            ob.data.update()
        before, recipe = digest(ob), ob.data[history.KEY]
        try:
            history.apply_recipe(ob, deepcopy(data), data['nodes'][0]['id'])
        except ValueError as error:
            assert 'unrecorded edits' in str(error)
        else:
            raise AssertionError('Stale history overwrote the mesh')
        assert digest(ob) == before and ob.data[history.KEY] == recipe


def test_linked_objects_remove_each_objects_shading_modifier_and_record_once():
    ob = cube(edit=False)
    other = ob.copy()
    bpy.context.scene.collection.objects.link(other)
    other.select_set(True)
    bpy.ops.object.shade_auto_smooth()
    assert menu.smooth_by_angle_mods(ob) and menu.smooth_by_angle_mods(other)
    bpy.ops.allset.soften_harden(angle=180)
    assert not menu.smooth_by_angle_mods(ob) and not menu.smooth_by_angle_mods(other)
    assert len(history.read(ob)['nodes']) == 1


def test_shading_and_empty_deletion_survive_native_save_load():
    ob = cube()
    bpy.ops.allset.soften_harden(angle=180)
    assert bpy.ops.allset.delete_components() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    name = ob.name
    path = Path(os.environ['BLENDER_USER_CONFIG']).parent/'shape_history.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    ob = bpy.data.objects[name]
    data = history.read(ob)
    assert len(data['nodes']) == 2 and len(ob.data.vertices) == 0
    history.edit(ob, data['nodes'][-1]['id'], {'enabled': False})
    assert len(ob.data.polygons) == 6 and all(face.use_smooth for face in ob.data.polygons)


def test_native_move_keeps_input_rows_and_replays_as_a_relative_tweak():
    ob = cube()
    pick_face(ob)
    bpy.ops.allset.extrude(thickness=.5)
    first = history.read(ob)['nodes'][0]
    bpy.ops.transform.translate(value=(1, 0, 0))
    history.invalidate()
    view = import_module(kit.MODULE+'.ui.in_view')
    ae = import_module(kit.MODULE+'.ui.attribute_editor')
    assert view.cb_record(bpy.context, ob).name == first['name']
    assert any(tab[1] == first['name'] for tab in ae.tabs(ob))
    assert float(bpy.context.window_manager.allset_history.thickness_text) == .5
    node = nodes.target(bpy.context)
    assert isinstance(node, nodes.HistoryNode)
    node.commit(bpy.context, dict(node.params, thickness=1))
    data = history.read(ob)
    assert [item['kind'] for item in data['nodes']] == ['FACE', 'TWEAK']
    bm = bmesh.from_edit_mesh(ob.data)
    assert abs(max(vertex.co.x for vertex in bm.verts)-2) < 1e-5
    pick_face(ob)
    bpy.ops.allset.extrude(thickness=.25)
    assert [item['kind'] for item in history.read(ob)['nodes']] == ['FACE', 'TWEAK', 'FACE']
    history.edit(ob, first['id'], dict(first['params'], thickness=.75))
    assert abs(max(vertex.co.x for vertex in bmesh.from_edit_mesh(ob.data).verts)-2) < 1e-5


def test_native_move_then_another_extrude_keeps_the_whole_chain():
    ob = cube()
    pick_face(ob)
    bpy.ops.allset.extrude(thickness=.5)
    first = history.read(ob)['nodes'][0]
    bpy.ops.transform.translate(value=(.2, .3, 0))
    bpy.ops.allset.extrude(thickness=.25)
    data = history.read(ob)
    assert [item['kind'] for item in data['nodes']] == ['FACE', 'TWEAK', 'FACE']
    assert len({item['id'] for item in data['nodes']}) == 3
    history.edit(ob, first['id'], dict(first['params'], thickness=1))
    assert abs(max(vertex.co.x for vertex in bmesh.from_edit_mesh(ob.data).verts)-1.2) < 1e-5


def test_topology_edits_keep_old_inputs_visible_then_baked_without_losing_geometry():
    ob = cube()
    pick_face(ob)
    bpy.ops.allset.extrude(thickness=.5)
    first = history.read(ob)['nodes'][0]
    bpy.ops.mesh.subdivide(number_cuts=1)
    history.invalidate()
    before_count = len(bmesh.from_edit_mesh(ob.data).verts)
    assert nodes.target(bpy.context) is not None
    ae = import_module(kit.MODULE+'.ui.attribute_editor')
    assert any(tab[1] == first['name'] for tab in ae.tabs(ob))
    before = digest(ob)
    try:
        history.edit(ob, first['id'], dict(first['params'], thickness=1))
    except ValueError:
        pass
    else:
        raise AssertionError('Unsupported topology was overwritten')
    assert digest(ob) == before
    bpy.ops.allset.soften_harden(angle=180)
    data = history.read(ob)
    assert data['baked'][0]['id'] == first['id']
    assert history.records(ob)[0].baked
    assert any(tab[1] == first['name']+' (baked)' for tab in ae.tabs(ob))
    history.edit(ob, data['nodes'][-1]['id'], dict(data['nodes'][-1]['params'], angle=0))
    assert len(bmesh.from_edit_mesh(ob.data).verts) == before_count


def test_seams_and_custom_attributes_force_safe_baking_and_survive_replay():
    ob = cube(edit=False)
    bpy.ops.allset.soften_harden(angle=180)
    ob.data.edges[0].use_seam = True
    attribute = ob.data.attributes.new('history_test_weight', 'FLOAT', 'POINT')
    attribute.data[0].value = .375
    history.invalidate()
    assert history.ensure(ob) is None
    bpy.ops.allset.soften_harden(angle=0)
    data = history.read(ob)
    assert len(data['baked']) == 1
    history.edit(ob, data['nodes'][-1]['id'], dict(data['nodes'][-1]['params'], angle=120))
    assert ob.data.edges[0].use_seam
    assert abs(ob.data.attributes['history_test_weight'].data[0].value-.375) < 1e-6


def test_creation_input_stays_visible_and_editable_after_native_vertex_move():
    cube(edit=False)
    prim = import_module(kit.MODULE+'.operators.prim_history')
    ob = prim.create_object(bpy.context, 'CUBE')
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    pick_face(ob)
    bpy.ops.allset.extrude(thickness=.5)
    bpy.ops.transform.translate(value=(.1, 0, 0))
    history.invalidate()
    ci = import_module(kit.MODULE+'.ui.creation_inputs')
    assert ci.has_node(ob)
    assert prim.rebuild(bpy.context, ob, {'width': 3})['width'] == 3
    assert history.read(ob)['nodes'][-1]['kind'] == 'TWEAK'


def test_legacy_signature_migrates_without_hiding_inputs():
    ob = cube(edit=False)
    bpy.ops.allset.soften_harden(angle=180)
    data = deepcopy(history.read(ob))
    data['version'] = 2
    data['result_hash'] = ex.mesh_coords_hash(ob.data, legacy=True)
    ob.data[history.KEY] = json.dumps(data)
    history.clear()
    assert history.read(ob)['version'] == history.VERSION
    assert history.ensure(ob) is not None
    history.edit(ob, data['nodes'][0]['id'], dict(data['nodes'][0]['params'], angle=0))
    assert history.read(ob)['version'] == history.VERSION


def test_native_scale_replays_exactly_after_another_operation():
    ob = cube()
    pick_face(ob)
    bpy.ops.allset.extrude(thickness=.5)
    bpy.ops.transform.resize(value=(.1, .1, .1))
    bpy.ops.allset.soften_harden(angle=180)
    data = history.read(ob)
    assert [node['kind'] for node in data['nodes']] == ['FACE', 'TWEAK', 'SOFT_EDGE']
    bm, checkpoint, _result, _moved = history._evaluate(ob, deepcopy(data))
    try:
        assert ex.coords_hash(bm) == data['result_hash']
    finally:
        bm.free()
        bpy.data.meshes.remove(checkpoint)


def test_primitive_move_before_first_extrusion_preserves_creation():
    cube(edit=False)
    prim = import_module(kit.MODULE+'.operators.prim_history')
    ob = prim.create_object(bpy.context, 'CUBE')
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    pick_face(ob)
    bpy.ops.transform.translate(value=(.1, 0, 0))
    assert import_module(kit.MODULE+'.ui.creation_inputs').has_node(ob)
    bpy.ops.allset.extrude(thickness=.5)
    data = history.read(ob)
    assert data['creation'] is not None
    assert [node['kind'] for node in data['nodes']] == ['TWEAK', 'FACE']
