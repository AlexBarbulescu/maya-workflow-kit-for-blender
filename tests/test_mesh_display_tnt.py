"""Mesh Display menu regressions for winding, edge selection, and color sets."""

from importlib import import_module

import bmesh
import bpy

import kit


options = import_module(kit.MODULE + ".operators.option_windows")
menu = import_module(kit.MODULE + ".ui.menu_sets")
status_line = import_module(kit.MODULE + ".ui.status_line")


def _strip():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    mesh = bpy.data.meshes.new("Mesh Display strip")
    mesh.from_pydata([(x, y, 0.0) for x in range(4) for y in (0, 1)], [],
                     [(0, 1, 3, 2), (2, 4, 5, 3), (4, 5, 7, 6)])
    ob = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    return ob


def test_conform_uses_the_majority_and_reverse_expands_the_shell():
    ob = _strip()
    try:
        assert bpy.ops.allset.menu_item(item="Mesh Display/Conform") == {'FINISHED'}
        assert all(p.normal.z < 0.0 for p in ob.data.polygons)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='FACE')
        bpy.ops.mesh.select_all(action='DESELECT')
        bm = bmesh.from_edit_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        bm.faces[1].select_set(True)
        window = options.find_path("Mesh Display/Reverse")
        assert options.run(window, bpy.context, {"scope": "All faces in the shell"}) == {'FINISHED'}
        bpy.ops.object.mode_set(mode='OBJECT')
        assert all(p.normal.z > 0.0 for p in ob.data.polygons)
        assert [f.index for f in ob.data.polygons if f.select] == [1]
    finally:
        if bpy.context.mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob, do_unlink=True)


def test_harden_edge_covers_coplanar_edges_and_skips_empty_selections():
    ob = _strip()
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        assert bpy.ops.allset.soften_harden(angle=0) == {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')
        assert not any(e.use_edge_sharp for e in ob.data.edges)
        assert bpy.ops.allset.menu_item(item="Mesh Display/Harden Edge") == {'FINISHED'}
        assert all(e.use_edge_sharp for e in ob.data.edges)
    finally:
        if bpy.context.mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(ob, do_unlink=True)


def test_color_set_options_and_apply_channel_mask():
    ob = _strip()
    view = status_line.view3d_space(bpy.context)
    saved = (view.shading.type, view.shading.color_type) if view is not None else None
    try:
        for name in ("Reverse", "Soften/Harden Edges", "Create Empty Set", "Apply Color"):
            assert menu.option_kind(f"Mesh Display/{name}") == "window"
        window = options.find_path("Mesh Display/Create Empty Set")
        assert options.run(window, bpy.context, {"name": "Daylight"}) == {'FINISHED'}
        attr = ob.data.color_attributes.active_color
        assert (attr.name, attr.domain, attr.data_type) == ("Daylight", 'CORNER', 'FLOAT_COLOR')
        window = options.find_path("Mesh Display/Apply Color")
        assert options.run(window, bpy.context, {"effect": "Individual Channels", "green": False, "blue": False,
                                                  "set_alpha": False, "color": (0.25, 0.0, 0.0)}) == {'FINISHED'}
        assert all(tuple(d.color) == (0.25, 1.0, 1.0, 1.0) for d in attr.data)
    finally:
        if saved is not None:
            view.shading.type, view.shading.color_type = saved
        bpy.data.objects.remove(ob, do_unlink=True)
