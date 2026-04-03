# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import logging
from pathlib import Path, PurePath
from typing import Any

import bpy  # pyright: ignore[reportMissingImports]

from blender_asset_tracer import path_rewriting_models

from . import file_usage, hashing
from .type_aliases import RewriteRules

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


def rewrite_file(rewrite_request: path_rewriting_models.RewriteRequest) -> None:
    """Perform path rewriting on the given file.

    NOTE: This opens the blend file as the main blend file.

    This function is meant to be called by the background packer process,
    see path_rewriting_worker.py.
    """
    assert rewrite_request.pack_source_root.is_absolute()
    assert rewrite_request.blendfile.is_absolute()
    assert not rewrite_request.relpath_in_root.is_absolute()
    assert rewrite_request.blendfile != rewrite_request.save_to

    # Define some local variables to shorten things.
    rr_blendfile = rewrite_request.blendfile
    rr_relpath_in_root = rewrite_request.relpath_in_root
    rr_rewrite_rules = rewrite_request.rewrite_rules
    rr_save_to = rewrite_request.save_to
    rr_pack_source_root = rewrite_request.pack_source_root

    # Construct the absolute directory path of the blend file in the pack.
    blendfile_abspath_in_pack = rr_pack_source_root / rr_relpath_in_root
    blend_dir_in_pack = blendfile_abspath_in_pack.parent

    def _rewrite_path_usage(owner_id: bpy.types.ID, path: str, _: Any) -> str | None:
        """Rewrite this file path, if it's absolute or in the rewrite rules."""

        # Make the file path an absolute pathlib.Path. This ensures
        # compatibility with the rewrite rules (which always contains absolute
        # paths). This MUST use the same function as
        # file_usage.dependencies_of_current_blendfile() uses.

        abs_path = file_usage.path_absolute(path, library=owner_id.library)

        # Construct the file's new absolute path, based on the rewrite rules.
        relocated_abs_path: Path
        try:
            abs_path_dir = abs_path.parent
            relocated_relpath = rr_rewrite_rules[abs_path_dir]
        except KeyError:
            # This KeyError means that there is no rewrite rule for this
            # directory. The path still needs remapping if it's absolute.

            # If the path is relative, it can be used as-is.
            if not file_usage.is_blender_path_absolute(path):
                _logger.info("  - keeping           : %s", path)
                return None

            _logger.info("  - making relative   : %s", path)
            relocated_abs_path = abs_path
        else:
            # Construct the absolute file path from the rewritten directory path.
            _logger.info("  - rewriting         : %s", path)
            relocated_abs_path = rr_pack_source_root / relocated_relpath / abs_path.name

        # The path is either absolute or relative to the project root in the
        # pack. It has to be rewritten so that it's relative to the blend file.
        _logger.info("    relocated_abs_path: %s", relocated_abs_path)
        _logger.info("    blend_dir_in_pack : %s", blend_dir_in_pack)
        blendfile_relative_path = relocated_abs_path.relative_to(
            blend_dir_in_pack, walk_up=True
        )
        rewritten_path_str = "//" + blendfile_relative_path.as_posix()
        _logger.info("    rewritten_path    : %s", rewritten_path_str)

        # It's possible that rewriting doesn't actually change the path. This
        # can happen when a relocated file references another relocated file,
        # and eventually end up in the same relative configuration.
        #
        # TODO: try to detect these cases before doing the rewriting, as that
        # may make it possible to just do a relocate (instead of no-op
        # rewriting).
        if rewritten_path_str == path:
            _logger.info("    nothing changed, skipping path")
            return None
        return rewritten_path_str

    try:
        with file_usage.cache_autoclear():
            _logger.info("Path-rewriting {!s}".format(rr_blendfile))

            # 1. Load the blend file.
            op_result = bpy.ops.wm.open_mainfile(filepath=str(rr_blendfile))
            if "FINISHED" not in op_result:
                raise RuntimeError(f"Could not open blend file {rr_blendfile}")

            # 2. Do the path remapping.
            bpy.data.file_path_foreach(_rewrite_path_usage)

            # 3. Save the blend file.
            _logger.info("Saving to {!s}".format(rr_save_to))
            rr_save_to.parent.mkdir(parents=True, exist_ok=True)
            op_result = bpy.ops.wm.save_as_mainfile(
                filepath=str(rr_save_to),
                copy=True,
                compress=True,
                # Never do remapping, as the 'rr_save_to' will likely be some cache
                # directory, and not anywhere near the location in the pack.
                relative_remap=False,
            )
            if "FINISHED" not in op_result:
                raise RuntimeError(f"Could not save blend file {rr_save_to}")
    finally:
        # Free memory by unloading the blend file.
        bpy.ops.wm.read_homefile(use_empty=True)


def _compute_ophash(blendfile: Path, file_info: file_usage.FileInfo) -> str:
    """Return the 'operation hash' for this blendfile + metadata.

    This is a fingerprint of the file's contents, hashed together with the
    rewrite rules and its final location in the BAT pack.
    """
    assert file_info.relpath_in_pack is not None, blendfile

    # Compute the file's hash.
    file_hasher = hashing.get_hasher()
    file_hash: str = file_hasher(blendfile)

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

    # Combine the file's hash with the rewrite rules to obtain the operation
    # hash.
    #
    # This hash algorithm is independent of the hash algo used to compute the
    # file hash, and so this should NOT reference hashing._hash_algorithm.
    hasher = hashlib.new("SHA256")
    hasher.update(file_hash.encode())
    hasher.update(b"\0")
    hasher.update(directory_in_pack.encode())
    hasher.update(b"\0")
    for rule in rules_for_hash:
        hasher.update(rule.encode())
        hasher.update(b"\0")
    ophash = hasher.hexdigest()

    return ophash
