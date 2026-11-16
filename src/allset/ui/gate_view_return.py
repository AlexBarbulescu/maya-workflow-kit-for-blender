# SPDX-License-Identifier: GPL-3.0-or-later
"""tnt: a gate button pressed in Blender's own perspective view looks through the view's startup camera (Maya's persp
panel is that camera). Turning the gates off again puts that view back to its own perspective, so Blender's camera
border (always drawn in a camera view) goes away like Maya's frame does. Views the user pointed at a camera
themselves are left alone.
"""

# RegionView3D pointer -> name of the camera a gate button made the view look through (session only)
_entered = {}


def entered(space, cam):
    if space.region_3d is not None and cam is not None:
        _entered[space.region_3d.as_pointer()] = cam.name


def _any_on(data):
    from .panel_state import FIELD_CHART, RES_GATE, SAFE
    # Gate Mask (show_passepartout) is left out: Blender cameras have it on by default
    return bool(data.show_sensor or data.get(RES_GATE) or data.get(FIELD_CHART)
                or any(data.get(flag) for flag, _attr in SAFE.values()))


def maybe_return(space, cam):
    """Back to the view's own perspective when a gate button entered this camera view and nothing gate-like is on."""
    rv3d = space.region_3d
    if rv3d is None or cam is None or cam.type != 'CAMERA':
        return
    ptr = rv3d.as_pointer()
    if _entered.get(ptr) != cam.name:
        return
    if rv3d.view_perspective != 'CAMERA':
        _entered.pop(ptr, None)
        return
    if _any_on(cam.data):
        return
    _entered.pop(ptr, None)
    rv3d.view_perspective = 'PERSP'
