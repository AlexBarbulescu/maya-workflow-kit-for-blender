# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep user normals attached to their face-vertices across a winding reversal."""

import bpy

from .normals_maya import current, write


def snapshot(meshes):
    bpy.ops.object.mode_set(mode='OBJECT')
    try:
        saved = {}
        for me in meshes:
            normals, locked = current(me)
            saved[me] = [
                {me.loops[c].vertex_index: normals[c] for c in face.loop_indices if locked[c]}
                for face in me.polygons
            ]
        return saved
    finally:
        bpy.ops.object.mode_set(mode='EDIT')


def restore(saved, targets, preserve):
    bpy.ops.object.mode_set(mode='OBJECT')
    try:
        for me, corners in saved.items():
            normals = [(0.0, 0.0, 0.0)] * len(me.loops)
            locked = [False] * len(me.loops)
            for face, before in zip(me.polygons, corners):
                flip = not preserve and face.index in targets[me]
                for c in face.loop_indices:
                    normal = before.get(me.loops[c].vertex_index)
                    if normal is not None:
                        normals[c] = tuple(-axis for axis in normal) if flip else normal
                        locked[c] = True
            write(me, normals, locked)
    finally:
        bpy.ops.object.mode_set(mode='EDIT')
