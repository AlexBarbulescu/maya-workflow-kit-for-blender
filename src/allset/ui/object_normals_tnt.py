# SPDX-License-Identifier: GPL-3.0-or-later
"""tnt: normals drawn on meshes outside edit mode, like Maya's Display > Polygons > Face / Vertex Normals.

Maya draws normals on a mesh in object mode. Blender draws its overlays (Face / Vertex / Split Normals, Normal Size)
only on meshes in edit mode, so the shelf's Toggle Normals and Display > Polygons > Face Normals / Normals Size...
showed nothing in object mode. This draws the same overlays, with the same switches, length and theme colours, on the
selected meshes that are not in edit mode (Blender draws the ones in edit mode itself). Uses the evaluated mesh
(modifiers on), like Maya's shaded result.
"""

import bpy
import numpy as np

KINDS = ("show_face_normals", "show_vertex_normals", "show_split_normals")

_handle = []
_cache = {}     # (object pointer, kind) -> (geometry stamp, matrix, length, batch)
_reported = []  # the first draw error, printed once
_stamp = [0]    # bumped on every geometry update: a cached batch with an older stamp is rebuilt


def _arr(seq, attr, n, width=3):
    out = np.empty(n * width, dtype=np.float32)
    seq.foreach_get(attr, out)
    return out.reshape(n, width)


def object_space(me, kind):
    """(points, unit directions) of one normals kind on mesh ``me``, in object space."""
    if kind == "show_face_normals":
        n = len(me.polygons)
        return _arr(me.polygons, "center", n), _arr(me.polygons, "normal", n)
    if kind == "show_vertex_normals":
        n = len(me.vertices)
        return _arr(me.vertices, "co", n), _arr(me.vertices, "normal", n)
    n = len(me.loops)
    vidx = np.empty(n, dtype=np.int32)
    me.loops.foreach_get("vertex_index", vidx)
    co = _arr(me.vertices, "co", len(me.vertices))
    return co[vidx], _arr(me.corner_normals, "vector", n)


def segments(points, dirs, matrix, length):
    """World-space line pairs: each point, then the point + its normal (world direction) * ``length``."""
    m = np.array(matrix, dtype=np.float32)
    p = points @ m[:3, :3].T + m[:3, 3]
    d = dirs @ np.linalg.inv(m[:3, :3])          # normals transform by the inverse transpose
    norm = np.linalg.norm(d, axis=1, keepdims=True)
    d = d / np.where(norm > 0, norm, 1) * length
    out = np.empty((len(p) * 2, 3), dtype=np.float32)
    out[0::2] = p
    out[1::2] = p + d
    return out


def _batch(ob, kind, depsgraph, length, shader):
    from gpu_extras.batch import batch_for_shader
    key = (ob.as_pointer(), kind)
    got = _cache.get(key)
    if got is not None and got[0] == _stamp[0] and got[1] == ob.matrix_world and got[2] == length:
        return got[3]
    me = ob.evaluated_get(depsgraph).data
    pts, dirs = object_space(me, kind)
    batch = None
    if len(pts):
        batch = batch_for_shader(shader, 'LINES', {"pos": segments(pts, dirs, ob.matrix_world, length)})
    if len(_cache) > 256:
        _cache.clear()
    _cache[key] = (_stamp[0], ob.matrix_world.copy(), length, batch)
    return batch


def _draw():
    context = bpy.context
    try:
        space = context.space_data
        ov = space.overlay
        kinds = [k for k in KINDS if getattr(ov, k)]
        if not kinds or not ov.show_overlays:
            return
        obs = [ob for ob in context.selected_objects
               if ob.type == 'MESH' and ob.mode != 'EDIT' and ob.visible_get(viewport=space)]
        if not obs:
            return
        import gpu
        theme = context.preferences.themes[0].view_3d
        colours = {"show_face_normals": theme.normal,      # Blender's theme name for the face normal colour "show_vertex_normals": theme.vertex_normal,
                   "show_split_normals": theme.split_normal}
        depsgraph = context.evaluated_depsgraph_get()
        sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        region = context.region
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.blend_set('ALPHA')
        try:
            sh.uniform_float("viewportSize", (region.width, region.height))
            sh.uniform_float("lineWidth", context.preferences.system.pixel_size)
            for kind in kinds:
                sh.uniform_float("color", (*colours[kind][:3], 1.0))
                for ob in obs:
                    batch = _batch(ob, kind, depsgraph, ov.normals_length, sh)
                    if batch is not None:
                        batch.draw(sh)
        finally:
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('NONE')
    except (ReferenceError, AttributeError, KeyError, ValueError, RuntimeError, TypeError) as ex:
        if not _reported:       # once: a draw handler error must not spam the console every redraw
            _reported.append(ex)
            print(f"Maya Workflow Kit: object-mode normals not drawn: {ex!r}")
        return


def _on_depsgraph(_scene, depsgraph):
    if any(u.is_updated_geometry for u in depsgraph.updates):
        _stamp[0] += 1


def register():
    if not _handle:
        _handle.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW'))
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def unregister():
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), 'WINDOW')
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    _cache.clear()
