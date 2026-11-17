"""tnt: paste a full path into any file browser's File Name box and press Enter to go there.

Blender turns the separators of a typed name into '_' when Enter is pressed (``I:\\a\\b`` -> ``I__a_b``), so only
dialogs with a Python ``check`` see the real text (the kit's Import/Export does). For every other dialog this reads
the '_' text back by walking the disk from the drive: each '_' is tried as a folder separator where such a folder
exists. A folder opens it and keeps the name that was in the box before the paste (as Maya does); an existing file
opens its folder with the file selected.

Dialogs whose ``check`` rewrites the path (Save As, every exporter: they add the extension) see the raw text first,
so Blender joins it to the current folder: folder ``C:\\scenes\\I:\\a\\`` + name ``b.blend``. A drive letter inside the
folder path can only come from such a paste (':' is not allowed in names), so that is read back the same way; a
missing file in an existing folder opens the folder with that name, ready to save."""

import os
import re

import bpy
from bpy.app.handlers import persistent

_OWNER = object()
_last = {}          # file browser area pointer -> File Name text before a paste
_DRIVE = re.compile(r'^_?([A-Za-z])__(.*)$')    # optional leading '_' = a pasted '"' quote
_EMBEDDED = re.compile(r'.+?[\\/]"?([A-Za-z]:[\\/].*)$')   # Windows: a pasted absolute path joined to the folder
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


def _looks_pasted(name):
    return "__" in name or name.startswith("_")


def _remember():
    """Timer: note each open file browser's File Name text, so a pasted folder can put it back (clicked names don't
    publish msgbus, so polling is the only way to see them)."""
    seen = set()
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            params = getattr(area.spaces.active, "params", None) if area.type == 'FILE_BROWSER' else None
            if params is None:
                continue
            key = area.as_pointer()
            seen.add(key)
            name = params.filename
            if name and not _EMBEDDED.match(params.directory.decode(errors="ignore")) and (not _looks_pasted(name)
                         or os.path.exists(os.path.join(params.directory.decode(errors="ignore"), name))):
                _last[key] = name
    for key in [k for k in _last if k not in seen]:     # dialog closed
        del _last[key]
    return 0.25


def last_name(area):
    """The File Name text ``area``'s file browser had before a path was pasted into it ("" if unknown)."""
    return _last.get(area.as_pointer(), "") if area else ""


def _embedded(params):
    """(folder, file name) for a path a ``check`` joined to the current folder, or None. The name is "" for a folder."""
    m = _EMBEDDED.match(params.directory.decode(errors="ignore")) if os.name == 'nt' else None
    if not m:
        return None
    raw = os.path.join(m.group(1), params.filename).replace('"', "")
    stem = os.path.splitext(raw)[0]
    if os.path.isdir(raw):
        return raw, ""
    if os.path.isdir(stem):
        return stem, ""                                         # check added the extension to a folder
    name = os.path.basename(raw)
    if name.startswith(".") and name.count(".") == 1 and os.path.isdir(os.path.dirname(raw)):
        return os.path.dirname(raw), ""                         # folder pasted with a trailing '\\'
    if os.path.isdir(os.path.dirname(raw)):
        return os.path.dirname(raw), os.path.basename(raw)      # a file (new or existing) in a real folder
    return None


def _on_filename(*_args):
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            space = area.spaces.active
            params = getattr(space, "params", None) if area.type == 'FILE_BROWSER' else None
            if params is None:
                continue
            try:
                found = _embedded(params) or (resolve(params.filename) if _looks_pasted(params.filename) else None)
            except (OSError, RecursionError):
                found = None
            if found:
                params.directory = os.path.join(found[0], "").encode()
                params.filename = found[1] or last_name(area)
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
    bpy.app.timers.register(_remember, first_interval=0.25, persistent=True)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.msgbus.clear_by_owner(_OWNER)
    if bpy.app.timers.is_registered(_remember):
        bpy.app.timers.unregister(_remember)
    _last.clear()
