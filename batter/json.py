# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import dataclasses
import functools
import json
from pathlib import Path

import bpy  # pyright: ignore[reportMissingImports]

__all__ = (
    "JSONEncoder",
    "dump",
    "dumps",
)


class JSONEncoder(json.JSONEncoder):
    """JSON encoder that can handle more types than the standard one.

    - Dataclasses: converted to object.
    - Set: converted to list.
    - Path: converted to string.
    - Library data-block: converted to string "<library /path/to/file.blend>".
    """

    def default(self, o: object) -> object:
        # `dataclasses.is_dataclass(o)` also returns True if `o` is a dataclass class.
        # This code only supports class instances, though.
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        if isinstance(o, set):
            return tuple(o)
        if isinstance(o, Path):
            return str(o)
        if isinstance(o, bpy.types.Library):
            return f"<library {o.filepath}>"
        return super().default(o)


# Wrap stdlib functions to use the above encoder.
dump = functools.partial(json.dump, cls=JSONEncoder, indent="  ")
dumps = functools.partial(json.dumps, cls=JSONEncoder, indent="  ")
