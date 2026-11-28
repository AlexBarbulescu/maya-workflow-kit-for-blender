# SPDX-License-Identifier: GPL-3.0-or-later
"""tnt: Maya Mesh Display > Set to Face (polySetToFaceNormal) on vertex-faces, like Maya.

Maya takes vertices or vertex-faces (a face selection = its vertex-faces) and gives each chosen vertex-face its face
normal; -setUserNormal makes them user (locked) normals, else they are computed (the vertex-faces become unshared).
Vertices with no chosen vertex-face keep their normals.

Blender keeps one normal per smooth fan, so a chosen corner is split from its neighbours with sharp edges (the two
edges of its face at its vertex). A sharp edge also splits the fan at its far vertex, which Maya leaves alone: corners
there whose normal would change keep the normal they had, as a custom (locked) normal.
"""

from mathutils import Vector

from .normals_maya import computed, current, write

SAME = 1e-4


def target_corners(me, verts, faces, face_mode):
    """Corners Maya sets: the selected faces' (face selection) or every corner of the selected vertices."""
    if face_mode:
        return {li for fi in faces for li in me.polygons[fi].loop_indices}
    return {li for li, loop in enumerate(me.loops) if loop.vertex_index in verts}


def set_to_face(me, targets, user_normal):
    """Give ``targets`` (corner indices) their face normal on mesh ``me`` (Object Mode)."""
    before, locked = current(me)
    normals = list(before)
    sharp = set()
    for poly in me.polygons:
        idx = list(poly.loop_indices)
        for k, li in enumerate(idx):
            if li in targets:
                normals[li] = tuple(poly.normal)
                locked[li] = user_normal
                sharp.add(me.loops[li].edge_index)
                sharp.add(me.loops[idx[k - 1]].edge_index)   # the face's other edge at this corner
    for ei in sharp:
        me.edges[ei].use_edge_sharp = True
    touched = {me.loops[li].vertex_index for li in targets}
    auto = computed(me)
    for li, loop in enumerate(me.loops):
        if (li not in targets and not locked[li] and loop.vertex_index not in touched
                and (Vector(auto[li]) - Vector(before[li])).length > SAME):
            locked[li] = True        # Maya didn't touch this vertex: keep the normal it had
    write(me, normals, locked)
