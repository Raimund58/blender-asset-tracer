# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Type aliases that are shared between various files in this module."""

__all__ = (
    "BlendFile",
    "RewriteRules",
)

from pathlib import Path, PurePath

import bpy  # pyright: ignore[reportMissingImports]

type BlendFile = bpy.types.Library | None
"""A .blend file represented by a Library; None indicates 'current file'."""


type RewriteRules = dict[Path, PurePath]
"""Mapping of {path on disk: path in pack}.

Maps an absolute path of a file to that file's new path in the pack (relative
to the pack's root).

This entire dict represents the rewrite rules for a single blend file. It contains
an entry for each relocated file that the blend file references.
"""
