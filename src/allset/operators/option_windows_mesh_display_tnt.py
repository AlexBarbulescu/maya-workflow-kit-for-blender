# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-operation settings for Mesh Display commands."""

import bpy

from .mesh_display_tnt import REVERSE_SCOPES
from .option_windows_modify import FString
from .option_windows_spec import F, Window


_SCOPES = {label: key for key, label, _description in REVERSE_SCOPES}
_COLOR_TYPES = {"Unclamped": 'FLOAT_COLOR', "Clamped (8-bit)": 'BYTE_COLOR'}
_DOMAINS = {"Face Corners": 'CORNER', "Vertices": 'POINT'}


def _create_set(context, v):
    return bpy.ops.allset.create_empty_color_set(name=v["name"], data_type=_COLOR_TYPES[v["range"]],
                                                 domain=_DOMAINS[v["domain"]])


WINDOWS = [
    Window("reverse_normals", "Reverse Normals Options", "Reverse Normals", None, [
        F("scope", "Reverse normals on:", "enum", "Selected faces", items=tuple(_SCOPES)),
        F("preserve", "", "bool", False, text="Preserve user normals direction"),
    ], lambda c, v: bpy.ops.allset.reverse_mesh_normals(scope=_SCOPES[v["scope"]],
                                                       preserve_user_normals=v["preserve"]),
        paths=("Mesh Display/Reverse",)),
    Window("soften_harden_edges", "Soften/Harden Edges Options", "Apply Smoothing", None, [
        F("method", "Harden by:", "enum", "Angle", items=("Angle", "Texture Borders")),
        F("angle", "Angle:", "float", 30.0, lo=0.0, hi=180.0),
    ], lambda c, v: bpy.ops.allset.soften_harden(angle=v["angle"], texture_borders=v["method"] == "Texture Borders"),
        paths=("Mesh Display/Soften/Harden Edges",),
        enabled=lambda v, name: name != "angle" or v["method"] == "Angle"),
    Window("create_empty_color_set", "Create Empty Color Set Options", "Create", None, [
        FString("name", "Name:", "colorSet1"),
        F("range", "Color Range:", "enum", "Unclamped", items=tuple(_COLOR_TYPES)),
        F("domain", "Store on:", "enum", "Face Corners", items=tuple(_DOMAINS)),
    ], _create_set, paths=("Mesh Display/Create Empty Set",),
        missing=("RGB / Alpha-only sets", "Per-instance color set sharing")),
]
