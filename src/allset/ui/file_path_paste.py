"""tnt: paste a full path into any file browser's File Name box and press Enter to go there.

Blender turns the separators of a typed name into '_' when Enter is pressed (``I:\\a\\b`` -> ``I__a_b``), so only
dialogs with a Python ``check`` see the real text (the kit's Import/Export does). For every other dialog this reads
the '_' text back by walking the disk from the drive: each '_' is tried as a folder separator where such a folder
exists. A folder opens it; an existing file opens its folder with the file selected."""

import os
import re

import bpy
from bpy.app.handlers import persistent

_OWNER = object()
_DRIVE = re.compile(r'^_?([A-Za-z])__(.*)$')    # optional leading '_' = a pasted '"' quote
_BAD = re.compile(r'[\x00-\x1f/\\?*:|"<>]')     # what BLI_path_make_safe_filename turns into '_'


def _same(a, b):
    return a.lower() == b.lower() if os.name == 'nt' else a == b


def _walk(folder, rest):
    """(folder, file name) that ``rest`` (a made-safe path below ``folder``) names on disk, or None."""
    if not rest:
        return folder, ""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return None
    for e in entries:
        safe = _BAD.sub("_", e.name)
        try:
            is_dir = e.is_dir()
        except OSError:
            continue
        if not is_dir:
            if _same(rest, safe) or _same(rest, safe + "_"):    # trailing '_' = a pasted closing quote
                return folder, e.name
        elif _same(rest, safe):
            return e.path, ""
        elif len(rest) > len(safe) and rest[len(safe)] == "_" and _same(rest[:len(safe)], safe):
            found = _walk(e.path, rest[len(safe) + 1:])
            if found:
                return found
    return None


def resolve(name):
    """(folder, file name) for a File Name box text that was a pasted absolute path, or None."""
    m = _DRIVE.match(name)
    if m:
        return _walk(m.group(1).upper() + ":\\", m.group(2))
    # shortcut: UNC (\\server\share) paths aren't read back; add when someone pastes network paths.
    if os.name != 'nt' and name.startswith("_") and len(name) > 1:
        return _walk("/", name[1:])
    return None


def _on_filename(*_args):
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            space = area.spaces.active
            params = getattr(space, "params", None) if area.type == 'FILE_BROWSER' else None
            if params is None or not ("__" in params.filename or params.filename.startswith("_")):
                continue
            try:
                found = resolve(params.filename)
            except (OSError, RecursionError):
                found = None
            if found:
                params.directory = os.path.join(found[0], "").encode()
                params.filename = found[1]
                area.tag_redraw()


def _subscribe():
    bpy.msgbus.clear_by_owner(_OWNER)
    bpy.msgbus.subscribe_rna(key=(bpy.types.FileSelectParams, "filename"), owner=_OWNER, args=(),
                             notify=_on_filename)


@persistent
def _on_load(*_args):
    _subscribe()        # a file load clears msgbus subscriptions


def register():
    _subscribe()
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.msgbus.clear_by_owner(_OWNER)

