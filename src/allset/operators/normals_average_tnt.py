# SPDX-License-Identifier: GPL-3.0-or-later
"""Average selected corner normals across objects in world space."""

from mathutils import Vector

from .normals_maya import SET_NORMAL, corners_of_verts, current, distance_groups, unit, write


def average_selection(selection, distance, replacement):
    positions = []
    entries = []
    meshes = {}
    for ob, verts, faces in selection.items():
        me = ob.data
        chosen = corners_of_verts(me, verts, faces if selection.face_mode else None)
        if not chosen:
            continue
        normals, locked = current(me)
        world_to_local = ob.matrix_world.to_3x3().transposed()
        local_to_world = world_to_local.inverted_safe()
        meshes[me] = (normals, locked)
        for v, corners in chosen.items():
            positions.append(ob.matrix_world @ me.vertices[v].co)
            contributions = [Vector(unit(local_to_world @ Vector(normals[c]))) for c in corners]
            entries.append((normals, locked, corners, world_to_local, sum(contributions, Vector())))

    fallback = Vector(unit(replacement))
    if not fallback.length_squared:
        fallback = Vector(SET_NORMAL)
    for group in distance_groups(positions, distance):
        total = sum((entries[v][4] for v in group), Vector())
        direction = total.normalized() if total.length > 1e-6 else fallback
        for v in group:
            normals, locked, corners, world_to_local, _sum = entries[v]
            normal = unit(world_to_local @ direction)
            for c in corners:
                normals[c] = normal
                locked[c] = True
    for me, (normals, locked) in meshes.items():
        write(me, normals, locked)
    return len(meshes)
