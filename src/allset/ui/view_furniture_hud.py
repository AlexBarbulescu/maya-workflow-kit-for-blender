"""Maya HUD section 9 lines (bottom right): Current Frame, Focal Length, Scene Timecode. A tnt addition kept in its
own module so upstream changes to view_furniture_draw merge without conflicts."""


def timecode(frame, fps):
    """Maya Scene Timecode text, hh:mm:ss:ff (frame 1 = 00:00:00:01, like Maya at time 0 + 1 frame)."""
    rate = max(1, round(fps))
    f = int(frame)
    s, ff = divmod(f, rate)
    m, ss = divmod(s, 60)
    hh, mm = divmod(m, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def hud_lines(prefs, scene, frame, lens):
    """Maya HUD section 9 lines (bottom right) in Maya's block order, bottom first: Frame (block 10),
    Focal Length (17), Scene Timecode (18). Hidden blocks take no space (shortcut: Maya's spacing of hidden blocks
    is unmeasured, check against a Maya screenshot if the stack looks off)."""
    out = []
    if prefs.maya_hud_current_frame:
        out.append(("Frame:", f"{frame:g}" if frame == int(frame) else f"{frame:.3f}"))
    if prefs.maya_hud_focal_length:
        out.append(("Focal Length:", f"{lens:.3f}"))
    if prefs.maya_hud_scene_timecode:
        out.append(("Scene Timecode:", timecode(frame, scene.render.fps / scene.render.fps_base)))
    return out


def draw_hud_lines(context, prefs, s):
    from .view_furniture_draw import _text
    from .view_furniture_geometry import LABEL_BASELINE, LABEL_PX, LABEL_RGB, TRIAD_INSET, _bounds, label_camera
    space, rv3d, scene = context.space_data, context.region_data, context.scene
    cam = label_camera(space, scene) if rv3d.view_perspective == 'CAMERA' else None
    lens = cam.data.lens if cam is not None and cam.type == 'CAMERA' else space.lens
    lines = hud_lines(prefs, scene, scene.frame_current + scene.frame_subframe, lens)
    if not lines:
        return
    import blf
    px = round(LABEL_PX * s)
    blf.size(0, px)
    label_w = max(blf.dimensions(0, a)[0] for a, _b in lines)
    data_w = max(blf.dimensions(0, b)[0] for _a, b in lines)
    _x0, y0, x1, _y1 = _bounds(context)
    x = x1 - TRIAD_INSET * s - data_w - 8 * s - label_w
    for i, (label, value) in enumerate(lines):
        y = y0 + LABEL_BASELINE * s + i * (px + 4 * s)
        _text(label, x, y, px, (*LABEL_RGB, 1.0), centre=False)
        _text(value, x + label_w + 8 * s, y, px, (*LABEL_RGB, 1.0), centre=False)
