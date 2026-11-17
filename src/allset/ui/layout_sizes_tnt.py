# SPDX-License-Identifier: GPL-3.0-or-later
"""tnt: the Outliner and right tab stack keep the widths the user dragged them to, across sessions.

The load-time fit (``layout_fit``) sized them to Maya's defaults on every start, so a layout the user had adjusted
came back at the kit's widths after the panels jumped there. Widths the user drags are stored per UI scale unit
(px / UI scale) in ``layout_sizes.json`` in the extension's user folder, and the fit uses them instead of the
defaults. A width change only counts as the user's when the window kept its size (Blender rescales every area
with the window) and no kit fit is running.
"""

import json
import os

import bpy

FILE = "layout_sizes.json"
_cache = [None]
_last = {}           # window pointer -> (window size, {key: width px})


def _path():
    try:
        return bpy.utils.extension_path_user(__package__.rsplit(".", 1)[0], path=FILE, create=False)
    except (ValueError, AttributeError):
        return None


def _load():
    if _cache[0] is None:
        _cache[0] = {}
        path = _path()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _cache[0] = {k: float(v) for k, v in data.items() if isinstance(v, (int, float)) and v > 0}
        except (OSError, TypeError, ValueError):
            pass
    return _cache[0]


def width(key, scale):
    """The width in px the user gave ``key`` ('OUTLINER', 'DOCK', 'DOCK_WIDE') at UI ``scale``, or None."""
    unit = _load().get(key)
    return None if unit is None else round(unit * scale)


def dock_key(kind):
    from .layout_fit import WIDE_KINDS
    return 'DOCK_WIDE' if kind in WIDE_KINDS else 'DOCK'


def _save(key, px, scale):
    data = _load()
    data[key] = round(px / scale, 2)
    path = _path()
    if path is None:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    except OSError as ex:
        print("Maya Workflow Kit: layout sizes not saved:", ex)


def _widths(window):
    """{key: width px} of the layout's Outliner (right of the Tool Box column) and the tab stack right of the main
    viewport, as the fit finds them."""
    from . import maya_dock
    from .layout_fit import GAP_PX, is_toolbox
    from .status_line import main_view3d
    screen = window.screen
    out = {}
    column = next((a for a in screen.areas if a.type == 'VIEW_3D' and is_toolbox(a.spaces.active)), None)
    if column is not None:
        outl = next((a for a in screen.areas if a.type == 'OUTLINER' and abs(a.x - (column.x + column.width)) <= GAP_PX
                     and a.height >= column.height - 4), None)
        if outl is not None:
            out['OUTLINER'] = outl.width
    dock = maya_dock.find_stack(screen)
    main, _r = main_view3d(screen)
    if dock is not None and main is not None and abs(main.x + main.width - dock.x) <= GAP_PX and dock.x > 2:
        out[dock_key(maya_dock.current_tab())] = dock.width
    return out


def sample(window, scale, busy):
    """Called by the fit tick for each window: while no fit is armed or running (``busy``), a width that changed
    while the window kept its size is the user's and is remembered."""
    ptr = window.as_pointer()
    if busy:
        _last.pop(ptr, None)
        return
    widths = _widths(window)
    size = (window.width, window.height)
    prev = _last.get(ptr)
    _last[ptr] = (size, widths)
    if prev is None or prev[0] != size:
        return
    for key, px in widths.items():
        old = prev[1].get(key)
        if old is not None and abs(px - old) > 2:
            _save(key, px, scale)


def forget():
    """A file load: the next tick only takes a baseline (its areas came from the file, not a drag)."""
    _last.clear()

