# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import logging
from pathlib import Path, PurePath
from typing import Any

import bpy  # pyright: ignore[reportMissingImports]

from . import file_usage
from .type_aliases import RewriteRules

_hash_storage_path = Path(bpy.app.cachedir) / "bat/path_rewrite_hashes"
_hash_method = "sha256"
_rewritten_files_cache_path = Path(bpy.app.cachedir) / "bat/path_rewrite_files"

_logger = logging.getLogger(__name__)


def path_in_cache(blendfile: Path, file_info: file_usage.FileInfo) -> Path:
    """Determine the path in the cache for the rewritten blend file.

    This uses Blender's Disk File Hash Service for efficiently computing the
    hash of blend files.
    """
    ophash = _compute_ophash(blendfile, file_info)
    path = _rewritten_files_cache_path / ophash[:2] / f"{ophash}.blend"
    return path


def determine_files_to_rewrite(
    deps_repo: file_usage.FileDependencyRepository,
) -> set[Path]:
    """Return set of files that need path rewriting.

    Sets the FileInfo.rewritten_file_path on all files that need path-rewriting.

    Returns the set of absolute paths of those files, but only if the result of
    the path rewriting wasn't cached yet.
    """

    # Determine the subset of the data that actually needs rewriting,
    # and for each file that does, determine its rewritten file path.
    blendfiles_to_rewrite: set[Path] = set()
    for abs_path, file_info in deps_repo.file_infoes.items():
        # Skip files that don't need rewriting.
        if not file_info.needs_path_rewriting:
            continue

        save_as = path_in_cache(abs_path, file_info)
        file_info.rewritten_file_path = save_as

        blendfiles_to_rewrite.add(abs_path)

    # Check the to-be-rewritten files, as they may have been cached already.
    for abs_path in blendfiles_to_rewrite.copy():
        file_info = deps_repo.file_infoes[abs_path]
        assert file_info.rewritten_file_path is not None

        if not file_info.rewritten_file_path.exists():
            # This one needs rewriting
            continue

        try:
            stat = file_info.rewritten_file_path.stat()
        except OSError:
            # If there was an issue reading the file now, it _may_ be ok once
            # it's been rewritten? Just give it a try.
            continue

        if stat.st_size == 0:
            # Zero-byte blend files are never valid, so re-attempt rewriting.
            continue

        # The cached file seems to be trustworthy, skip rewriting it.
        blendfiles_to_rewrite.remove(abs_path)

    return blendfiles_to_rewrite


def rewrite_file(
    blendfile: Path,
    blendfile_path_in_pack: PurePath,
    rewrite_rules: RewriteRules,
    save_to: Path,
) -> None:
    """Perform path rewriting on the given file.

    NOTE: This opens the blend file as the main blend file.

    This function is meant to be called by the background packer process,
    see path_rewriting_worker.py.

    :param blendfile: absolute path to the file to operate on.
    :param blendfile_path_in_pack: the blend file's location in the pack,
        relative to the pack's root.
    :param rewrite_rules: mapping from absolute file path, to that file's
        location in the pack.
    :param save_to: absolute path to where to save the rewritten file.
    """
    assert blendfile.is_absolute()
    assert not blendfile_path_in_pack.is_absolute()
    assert rewrite_rules, "cannot rewrite paths without rewrite rules"
    assert blendfile != save_to

    blend_dir_in_pack = blendfile_path_in_pack.parent

    def _rewrite_path_usage(owner_id: bpy.types.ID, path: str, _: Any) -> str | None:
        """Rewrite this file path, if it's in the rewrite rules."""

        # Make the file path an absolute pathlib.Path. This ensures
        # compatibility with the rewrite rules (which always contains absolute
        # paths). This MUST use the same function as
        # file_usage.dependencies_of_current_blendfile() uses.

        abs_path = file_usage.path_absolute(path, library=owner_id.library)

        # Look up the file's directory in the rewrite rules.
        abs_path_dir = abs_path.parent
        try:
            rewritten_dir_path_in_pack = rewrite_rules[abs_path_dir]
        except KeyError:
            _logger.info("  - keeping {!s}".format(abs_path))
            return None

        # Construct the rewritten file path.
        rewritten_path_in_pack = rewritten_dir_path_in_pack / abs_path.name

        # The path is relative to the project root in the pack. It has to be
        # rewritten so that it's relative to the loaded blend file.
        blendfile_relative_path = rewritten_path_in_pack.relative_to(
            blend_dir_in_pack, walk_up=True
        )
        rewritten_path_str = "//" + blendfile_relative_path.as_posix()

        # It's possible that rewriting doesn't actually change the path. This
        # can happen when multiple files refer to relocated files, but
        # eventually end up in the same relative configuration.
        #
        # TODO: try to detect these cases before doing the rewriting, as that
        # may make it possible to just do a relocate (instead of no-op
        # rewriting).
        if rewritten_path_str == path:
            return None

        _logger.info("  - mapping {!s} -> {!s}".format(path, rewritten_path_str))
        return rewritten_path_str

    with file_usage.cache_autoclear():
        _logger.info("Path-rewriting {!s}".format(blendfile))

        # 1. Load the blend file.
        op_result = bpy.ops.wm.open_mainfile(filepath=str(blendfile))
        if "FINISHED" not in op_result:
            raise RuntimeError(f"Could not open blend file {blendfile}")

        # 2. Do the path remapping.
        bpy.data.file_path_foreach(_rewrite_path_usage)

        # 3. Save the blend file.
        _logger.info("Saving to {!s}".format(save_to))
        save_to.parent.mkdir(parents=True, exist_ok=True)
        op_result = bpy.ops.wm.save_as_mainfile(
            filepath=str(save_to),
            copy=True,
            compress=True,
            # Never do remapping, as the 'save_to' will likely be some cache
            # directory, and not anywhere near the location in the pack.
            relative_remap=False,
        )
        if "FINISHED" not in op_result:
            raise RuntimeError(f"Could not save blend file {save_to}")


def _compute_ophash(blendfile: Path, file_info: file_usage.FileInfo) -> str:
    """Return the 'operation hash' for this blendfile + metadata.

    This is a fingerprint of the file's contents, hashed together with the
    rewrite rules and its final location in the BAT pack.
    """
    assert file_info.relpath_in_pack is not None, blendfile

    # For now, this is a library internal to Blender. It was made with BAT in mind
    # though, so once it's seen some production use, it's probably going to be
    # promoted to a public API.
    from _bpy_internal import (  # pyright: ignore[reportMissingImports]
        disk_file_hash_service as dfhs,
    )

    # Compute the file's hash.
    hash_service = dfhs.get_service(_hash_storage_path)
    file_hash: str = hash_service.get_hash(blendfile, _hash_method)

    # The file's `relpath_in_pack` is also important, as that determines the
    # relative paths to the files. The destination paths of the rewrite rules
    # are always relative to the pack root, and so they don't change when the
    # blend file itself is moved (hence their hash stays the same).
    #
    # The filename doesn't matter, only the directory, hence the `.parent`. This
    # way the cached blend file is still good when the file gets renamed.
    directory_in_pack = str(file_info.relpath_in_pack.parent)

    # Sort the rewrite rules for reproducibility. The POSIX notation is used
    # here to ensure the produced hash is the same on Windows and POSIX
    # platforms.
    #
    # WARNING: This is JUST for the hashing. In general this should NOT be done,
    # as it potentially changes UNC notation (`\\SERVER\Share\path`) to
    # blendfile-relative paths (`//path/to/asset`).
    rules_for_hash = sorted(
        f"{key.as_posix()}:{value.as_posix()}"
        for key, value in file_info.rewrite_rules.items()
    )

    # Combine the file's hash with the rewrite rules to obtain the operation hash.
    hasher = hashlib.new(_hash_method)
    hasher.update(file_hash.encode())
    hasher.update(b"\0")
    hasher.update(directory_in_pack.encode())
    hasher.update(b"\0")
    for rule in rules_for_hash:
        hasher.update(rule.encode())
        hasher.update(b"\0")
    ophash = hasher.hexdigest()

    return ophash
