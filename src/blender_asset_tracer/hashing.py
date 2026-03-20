# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

from collections.abc import Callable
from functools import partial
from pathlib import Path

_hash_algorithm = "sha256"

# Storage path relative to bpy.app.cachedir.
_hash_storage_cache_path = "bat/file_hashes"


def get_hasher() -> Callable[[Path], str]:
    """Return a callable that computes the hash of a file.

    Internally this uses Blender's DiskFileHashService for efficiently cached
    hash computation.
    """

    import bpy  # pyright: ignore[reportMissingImports]

    # For now, this is a library internal to Blender. It was made with BAT in mind
    # though, so once it's seen some production use, it's probably going to be
    # promoted to a public API.
    from _bpy_internal import (  # pyright: ignore[reportMissingImports]
        disk_file_hash_service as dfhs,
    )

    hash_storage_path = Path(bpy.app.cachedir) / _hash_storage_cache_path
    hash_service = dfhs.get_service(hash_storage_path)
    return partial(hash_service.get_hash, hash_algorithm=_hash_algorithm)
