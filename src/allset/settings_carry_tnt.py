# SPDX-License-Identifier: GPL-3.0-or-later
"""tnt: keep the kit's settings across Remove + reinstall and Blender version changes.

Everything the kit remembers sits in the extension's user folder (``preferences_backup.json``, ``shelves.json``,
``viewport_settings.json``, ``layout_sizes.json``, ``window_places.json``, marking menus...) and in Blender's add-on
preferences. Blender's Remove deletes both, and a new Blender version folder starts without them. So every
unregister copies the folder's top-level .json files into one file in Blender's version-independent user folder
(``%APPDATA%\\Blender Foundation\\Blender\\``), and a register that finds fresh preferences writes back the files that
are missing, then lets ``preferences.restore_backup`` put the settings back (Maya mode and key edits included).
"""

import json
import os

import bpy

from . import preferences

FILE = "maya_workflow_kit_tnt_settings.json"


def _paths():
    """(carry file, extension user folder), or (None, None) in a --factory-startup session / legacy add-on."""
    backup = preferences._backup_path()
    user = bpy.utils.resource_path('USER')
    # A sandboxed session (the kit's tests set BLENDER_USER_EXTENSIONS) must not touch the real user's copy.
    same = os.path.normcase(os.path.abspath(bpy.utils.user_resource('EXTENSIONS'))) == \
        os.path.normcase(os.path.abspath(os.path.join(user, "extensions")))
    if not backup or not same:
        return None, None
    return os.path.join(os.path.dirname(user), FILE), os.path.dirname(backup)


def _user_files(folder):
    return [n for n in os.listdir(folder)
            if n.endswith(".json") and ".bak" not in n and os.path.isfile(os.path.join(folder, n))]


def save():
    """Copy the user folder's settings files into the carry file (after ``preferences.save_backup``)."""
    try:
        carry, folder = _paths()
        if not carry or not os.path.isfile(os.path.join(folder, preferences.BACKUP_FILE)):
            return
        files = {}
        for name in _user_files(folder):
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                files[name] = fh.read()
        # shortcut: a kit whose settings are all at their defaults keeps the older copy; Remove + reinstall then
        # brings that copy back. Upgrade if "back to defaults" must also carry over.
        if files.get(preferences.BACKUP_FILE, "{}").strip() in ("", "{}"):
            return
        tmp = carry + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"files": files}, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, carry)
    except Exception as ex:                      # never stop the add-on from unregistering
        print("Maya Workflow Kit: could not keep a copy of the settings:", ex)


def restore():
    """Fresh preferences (after Remove or in a new Blender): write back the missing files and settings."""
    try:
        carry, folder = _paths()
        p = preferences._addon_prefs()
        if not carry or p is None or not os.path.isfile(carry):
            return
        if any(p.is_property_set(n) for n in preferences._names()):
            return                               # Blender or the user folder's backup kept the settings: they win
        with open(carry, encoding="utf-8") as fh:
            files = json.load(fh).get("files")
        if not isinstance(files, dict):
            return
        os.makedirs(folder, exist_ok=True)
        for name, text in files.items():
            path = os.path.join(folder, os.path.basename(name))
            if isinstance(text, str) and name.endswith(".json") and not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
        done = preferences.restore_backup()
        print(f"Maya Workflow Kit: settings brought back from {carry} ({len(done)} preference(s))")
    except Exception as ex:
        print("Maya Workflow Kit: could not bring the settings back:", ex)
