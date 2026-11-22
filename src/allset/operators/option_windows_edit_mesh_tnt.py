# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-operation options for Edit Mesh commands that use existing mesh operators."""

from .option_windows_spec import F, Window, _components, _k


WINDOWS = [
    Window("add_divisions", "Add Divisions Options", "Add Divisions", None, [
        F("divisions", "Cuts:", "int", 1, lo=1, hi=10),
        F("smoothness", "Smoothness:", "float", 0.0, lo=0.0, hi=1.0)],
        lambda c, v: _components(c, "allset.subdivide", 'FACE', divisions=v["divisions"], smoothness=v["smoothness"]),
        paths=("Edit Mesh/Add Divisions",)),
    Window("average_vertices", "Average Vertices Options", "Average Vertices", None, [
        F("iterations", "Iterations:", "int", 10, lo=0, hi=100)],
        lambda c, v: _components(c, "allset.average_vertices", 'VERT', iterations=v.get("iterations", 10)),  # old saved settings: "repeat"
        paths=("Edit Mesh/Average Vertices",)),
    Window("poke_faces", "Poke Options", "Poke", None, [F("offset", "Normal offset:", "length", 0.0)],
        lambda c, v: _components(c, "mesh.poke", 'FACE', offset=v["offset"] * _k(c), use_relative_offset=False),
        paths=("Edit Mesh/Poke",)),
]
