# SPDX-License-Identifier: GPL-3.0-or-later
"""tnt: a gate button in Blender's own view looks through the view's startup camera (Maya's persp / top / front / side
panel is that camera). When the last gate goes off in a view looking through a startup camera, the view goes back to
its own perspective / orthographic view, placed where the camera is, so Blender's camera border (always drawn in a
camera view, no Python switch) goes away like Maya's frame. Checked on the camera, not remembered per session: the kit
restores a panel's camera view after a reload or restart. Views through other cameras keep the camera view.
"""

from mathutils import Vector


def _any_on(data):
    from .panel_state import FIELD_CHART, RES_GATE, SAFE
    # Gate Mask (show_passepartout) is left out: Blender cameras have it on by default
    return bool(data.show_sensor or data.get(RES_GATE) or data.get(FIELD_CHART)
                or any(data.get(flag) for flag, _attr in SAFE.values()))


def maybe_return(space, cam):
    rv3d = space.region_3d
    if rv3d is None or cam is None or cam.type != 'CAMERA' or rv3d.view_perspective != 'CAMERA':
        return
    from ..operators import startup_cameras
    if not startup_cameras.is_startup(cam) or _any_on(cam.data):
        return
    loc, rot, _scale = cam.matrix_world.decompose()
    rv3d.view_rotation = rot
    rv3d.view_location = loc + rot @ Vector((0.0, 0.0, -rv3d.view_distance))   # view pivots in front of the camera
    rv3d.view_perspective = 'ORTHO' if cam.data.type == 'ORTHO' else 'PERSP'
