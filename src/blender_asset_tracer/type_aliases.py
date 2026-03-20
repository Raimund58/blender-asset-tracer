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

Maps an absolute path of a directory to that directory's new path in the pack
(relative to the pack's root). Filenames cannot be remapped, and will remain
the same.

A rewrite rule does NOT cover any subdirectories. Those need to have explicit
rules too. This is not a design choice, just a side-effect of the current
implementation.

This entire dict represents the rewrite rules for a single blend file. It contains
an entry for each directory of relocated files that the blend file references.
"""
