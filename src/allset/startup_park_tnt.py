# SPDX-License-Identifier: GPL-3.0-or-later
"""tnt: the start-up Maya layout is fitted before its first frame.

``screen.area_move`` (the load-time fit, ``ui/layout_fit.py``) refuses to run while the mouse is over a region,
and Blender sets a loaded screen's active region from the last mouse position. With the mouse over the window at
start-up the fit fell back to its cursor-warp fit a few ticks later, so the Outliner, tab stack, Tool Box column and
shelf row visibly jumped. Right before the new Maya scene loads (``first_start._open_layout``) the mouse is parked
on the window's left border (no region there in any layout; ``cursor_warp`` sets Blender's last mouse position at
once, so nothing has to wait for the OS event, which drew a frame of Blender's own UI first); the scene loads, is
fitted in one pass, and the mouse goes back. Windows only (the place to go back to is read with GetCursorPos);
elsewhere nothing changes.
"""

import sys

_saved = [None]      # screen point the mouse goes back to


def park(window):
    if sys.platform != "win32" or window is None:
        return
    from .ui.layout_fit import auto_warp
    if not auto_warp():
        return
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return
        _saved[0] = (pt.x, pt.y)
        window.cursor_warp(0, window.height // 2)
    except Exception:
        _saved[0] = None


def restore():
    point, _saved[0] = _saved[0], None
    if point is None:
        return
    try:
        import ctypes
        ctypes.windll.user32.SetCursorPos(*point)
    except Exception:
        pass
