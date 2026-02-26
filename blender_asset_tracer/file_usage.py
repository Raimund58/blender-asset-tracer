# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import contextlib
import dataclasses
import functools
import os.path
from collections.abc import Generator
from pathlib import Path, PurePath
from typing import Any

import bpy  # pyright: ignore[reportMissingImports]

from . import path_clustering
from .type_aliases import BlendFile, RewriteRules

__all__ = (
    "FileInfo",
    "FileDependencyRepository",
    "dependencies_of_current_blendfile",
    "determine_pack_paths_clustered",
    "determine_pack_paths_simple",
    "path_absolute",
    "library_abspath",
    "library_is_archive",
    "cache_clear",
    "determine_rewriting_needs",
)


@dataclasses.dataclass(frozen=True)
class Options:
    # Only include dependencies that are referred to by a relative path.
    # When False, include all dependencies.
    #
    # NOTE: This does _not_ cover blend files. These are always included,
    # regardless of how they are referenced.
    use_relative_only: bool = False


@dataclasses.dataclass
class FileInfo:
    # Indicator that this file needs relocation.
    #
    # `relpath_in_pack` is only allowed to be None if this is True.
    # This field remains set, even after `relpath_in_pack` is determined for
    # relocated files as well.
    needs_relocation: bool = False

    # Indicator that this file needs path rewriting.
    #
    # This means that this file referenced a file that has `needs_relocation=True`.
    needs_path_rewriting: bool = False

    # The path, relative to the project root, where this file will sit on the
    # farm. For to-be-relocated paths, this is initially None, as determining
    # that requires a more global view of all files that need relocating.
    relpath_in_pack: PurePath | None = None

    # Library files that contain data-blocks that reference this file.
    references: set[BlendFile] = dataclasses.field(default_factory=set)

    # Rewrite rules that should be applied to this file.
    # Should only be set when `needs_path_rewriting=True`.
    rewrite_rules: RewriteRules = dataclasses.field(default_factory=dict)

    # Absolute path of the file's location after it had its paths rewritten.
    rewritten_file_path: Path | None = None


@dataclasses.dataclass
class FileDependencyRepository:
    """Collection of FileInfo objects for each file."""

    # The absolute root path of the project. This is used to determine whether relocation is needed or not.
    root_path: Path

    # Mapping from absolute path to FileInfo.
    file_infoes: dict[Path, FileInfo] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        assert self.root_path.is_absolute()

    def add_file(self, abspath: Path, *, used_by_library: BlendFile) -> FileInfo:
        """Add a file to the repository.

        :param abspath: Absolute path of the file. This can be an external asset
           (like a `.png`) or a `.blend` file.
        :param used_by_library: the Library data-block (or None, if the current
           blend file) that uses this file.
        """
        try:
            file_info = self.file_infoes[abspath]
        except KeyError:
            pass
        else:
            # Remember that this library blend file references this asset file.
            file_info.references.add(used_by_library)
            return file_info

        # Construct all the file info. Most of this code just depends on the
        # file's path and the root path, which means it doesn't have to be
        # repeated for every ID that uses it.
        file_info = FileInfo()
        self.file_infoes[abspath] = file_info

        # Remember that this library blend file references this asset file.
        file_info.references.add(used_by_library)

        try:
            relpath_in_pack = PurePath(abspath.relative_to(self.root_path))
        except ValueError:
            # This file does not sit within the project root, and so needs relocation.
            # It will be handled later, when all relocations are known.
            file_info.needs_relocation = True
            file_info.relpath_in_pack = None
        else:
            # This file can be used as referenced.
            file_info.needs_relocation = False
            file_info.relpath_in_pack = PurePath(relpath_in_pack)

        return file_info


def dependencies_of_current_blendfile(
    root_path: Path,
    options: Options = Options(),
) -> FileDependencyRepository:
    """Return info about all files used by the currently-open blend file.

    This includes the currently-open blend file itself, so that the returned
    data is a complete picture of all relevant files.
    """

    with cache_autoclear():
        deps_repo = FileDependencyRepository(root_path=root_path)
        determine_dependencies(deps_repo, options)
        determine_pack_paths_clustered(deps_repo)
        determine_rewriting_needs(deps_repo)

    return deps_repo


def determine_dependencies(
    deps_repo: FileDependencyRepository,
    options: Options = Options(),
) -> None:
    """Return info about all files used by the currently-open blend file.

    Returns a mapping from absolute file path, to a FileInfo about that file.
    This includes the currently-open blend file itself, so that the returned
    data is a complete picture of all relevant files.

    When a file sits outside the given root path, the FileInfo will be marked
    as "needs relocation", and the path in the pack will be None.
    """

    # Add the current blend file itself.
    deps_repo.add_file(library_abspath(None), used_by_library=None)

    # Step 1: find all inter-blendfile relations.
    for used_id, ids_using_some_id in bpy.data.user_map().items():
        if not ids_using_some_id:
            continue

        used_library = used_id.library
        if library_is_packed(used_library) or library_is_archive(used_library):
            # Not actually a file on disk.
            continue

        used_lib_path = library_abspath(used_library)

        for id_user in ids_using_some_id:
            if id_user.library == used_library:
                continue

            # id_user_lib_path = library_abspath(used_library)
            deps_repo.add_file(used_lib_path, used_by_library=id_user.library)

    # Step 2: find all paths to non-blendfiles.
    def _visit_path_usage(owner_id: bpy.types.ID, path: str, _: Any) -> str | None:
        """Track each file path used.

        Always return None, to indicate to Blender that this path doesn't need
        rewriting (not now, anyway).
        """
        if owner_id.id_type == "LIBRARY":
            # Skip library data-blocks. They only indicate the use of the
            # library, but give us no information about recursive dependencies.
            return None

        if options.use_relative_only and _is_blender_path_absolute(path):
            # Skip absolute paths.
            return None

        abspath = path_absolute(path, library=owner_id.library)
        deps_repo.add_file(abspath, used_by_library=owner_id.library)
        return None

    bpy.data.file_path_foreach(_visit_path_usage)


def determine_pack_paths_clustered(repo: FileDependencyRepository) -> None:
    """Update all the files in the repository so they know their path in the pack.

    Sets file_info.relpath_in_pack for each file in repo.file_infoes.

    This determines clusters of out-of-project paths, so that each cluster can
    be stored in as short a path as possible.
    """

    # This is the root directory (relative to the project root in the pack).
    relocated_root = Path("_outside_project")

    # Cluster all paths that need relocation, in order to determine shorter packed paths.
    abs_paths = [
        abs_path
        for abs_path, file_info in repo.file_infoes.items()
        if file_info.needs_relocation
    ]

    if not abs_paths:
        # No relocation necessary.
        return

    clusters = path_clustering.build_clusters(abs_paths)

    # Shorten the cluster roots, keeping in mind that they should remain unique.
    shorten_cluster_map = _shorten_paths(list(clusters.keys()))

    for cluster_root, relpaths in clusters.items():
        short_root = shorten_cluster_map[cluster_root]
        for relpath in relpaths:
            relpath_in_pack = relocated_root / short_root / relpath
            abs_path = cluster_root / relpath
            file_info = repo.file_infoes[abs_path]
            file_info.relpath_in_pack = relpath_in_pack


def _shorten_paths(paths: list[Path]) -> dict[Path, Path]:
    """Determine the shortest paths possible while keeping them unique.

    Returns mapping {path: shortened version of that path}.
    """

    max_suffix_size = max(len(path.parts) for path in paths)

    # TODO: make this smarter:
    # - Use a counter per conflict, instead of globally.
    # - Alternate between taking a suffix and a prefix.
    shortened_prefixes: dict[Path, Path] = {}
    for suffix_size in range(1, max_suffix_size + 1):
        shortened_prefixes.clear()

        for cluster_prefix in paths:
            # Take the last N parts of the cluster prefix, hoping that that'll make things unique.
            short_parts = cluster_prefix.parts[-suffix_size:]
            shortened = cluster_prefix.with_segments(*short_parts)

            # If there are collisions, this will overwrite an already-existing value.
            # That's fine, it'll get detected later.
            shortened_prefixes[shortened] = cluster_prefix

        if len(shortened_prefixes) == len(paths):
            # Every path had a unique prefix.
            break
    else:
        # Impossible to shorten, which means there were duplicates. This should
        # not have happened, because the paths come from the clustering
        # algorithm, and were keys in a dictionary.
        raise RuntimeError(f"Could not shorten these paths: {paths!r}")

    # Flip the dictionary, so that it can be keyed by original (not shortened) path.
    return {orig: short for short, orig in shortened_prefixes.items()}


def determine_pack_paths_simple(repo: FileDependencyRepository) -> None:
    """Update all the files in the repository so they know their path in the pack.

    Sets file_info.relpath_in_pack for each file in repo.file_infoes.

    This simply puts the files into "./_outside_project/{absolute path}".
    """

    # This is the root directory (relative to the project root in the pack).
    relocated_root = Path("_outside_project")

    for abs_path, file_info in repo.file_infoes.items():
        if not file_info.needs_relocation:
            continue
        rel_path = _path_relative_safe(abs_path)
        file_info.relpath_in_pack = relocated_root / rel_path


def path_absolute(
    blender_path: str | Path, library: bpy.types.Library | None = None
) -> Path:
    """Make the path absolute, normalize it, and resolve its upper/lower case."""

    if isinstance(blender_path, str):
        # Use Blender to resolve blendfile-relative paths (starting with '//') to absolute paths.
        # This does _not_ resolve '..' components, symlinks, etc.
        absolute: str = bpy.path.abspath(blender_path, library=library)
    else:
        assert library is None, "only strings can be used as library-relative paths"
        absolute = str(blender_path.absolute())

    # Normalize to remove '..' components. Do this via os.path, because pathlib
    # always follows symlinks for this. This may bite us in the rear if there
    # are symlinks, because 'symlinked_dir/../subdir' is NOT the same as
    # 'subdir'.
    #
    # These '..' components need to be removed. abs_path.relative_to(root_path)
    # will happily walk out of the root path, if there are enough '..'
    # components.
    absolute = os.path.abspath(absolute)

    # Use Blender to resolve upper/lower case. This is necessary when dealing
    # with blend files created on Windows.
    case_resolved = bpy.path.resolve_ncase(absolute)

    as_path = Path(case_resolved)
    assert ".." not in as_path.parts, '".." should have been resolved in {!r}'.format(
        as_path
    )
    return as_path


def _path_relative_safe(some_path: PurePath) -> PurePath:
    """Remove the root/anchor from the path, and remove '..' entries.

    This turns the path into a relative one, that's safe to concatenate
    to another path without it escaping.
    """

    parts = list(some_path.parts)

    # Remove the anchor/root entry. For UNC notation this is the entire `\\SERVER\share` part.
    if some_path.is_absolute():
        parts = parts[1:]

    # Remove `..` entries. If there is a directory entry preceeding the ''..', that is removed too. Otherwise the '..'
    i = 0
    while i < len(parts):
        if parts[i] != "..":
            i += 1
            continue

        if i == 0:
            parts = parts[1:]
            continue

        parts = parts[: i - 1] + parts[i + 1 :]
        i -= 1

    # some_path.with_segments() ensures that the returned path is of the same type as 'some_path'.
    return some_path.with_segments(*parts)


def _is_blender_path_absolute(path_from_blender: str) -> bool:
    """Return True when the path is an absolute path.

    For this function, "absolute" is considered a path that remains valid when
    the blend file moves to a different directory.

    This does _not_ use pathlib, as it needs to handle Windows paths on Linux
    and vice versa.
    """
    if not path_from_blender:
        # Empty path is relative by definition.
        return False

    if len(path_from_blender) >= 2:
        match path_from_blender[:2]:
            case "//":
                # Blendfile-relative.
                return False
            case r"\\":
                # Windows, UNC notation, and that's always absolute.
                return True
            case _ if path_from_blender[0].isalpha() and path_from_blender[1] == ":":
                # Drive letter, is absolute.
                return True

    match path_from_blender[0]:
        case "/":
            # POSIX path, absolute.
            return True
        case "\\":
            # Windows path. This is kind of relative, because it's relative to
            # the current drive.
            return True

    # All other cases are considered relative.
    return False


@functools.lru_cache
def library_abspath(lib: BlendFile | None) -> Path:
    """Return the absolute path to the library.

    lib=None returns the absolute path of the current blend file.
    """
    if lib is None:
        filepath = bpy.data.filepath
    else:
        assert lib.packed_file is None, (
            f"only non-packed libraries have an absolute path: {lib} is packed"
        )
        filepath = bpy.path.abspath(lib.filepath)
    return path_absolute(filepath)


def library_is_packed(lib: BlendFile) -> bool:
    if lib is None:
        return False
    return lib.packed_file is not None


@functools.lru_cache
def library_is_archive(lib: BlendFile) -> bool:
    """Check for 'archive libraries', used for 'packed assets'.

    See:
        - [Virtual Library Technical Design][1]
        - [Data-Block Embedding Technical Design][2]

    [1]: https://projects.blender.org/blender/blender/issues/132170
    [2]: https://projects.blender.org/blender/blender/issues/132167
    """
    if lib is None:
        return False

    if lib.is_archive:
        return True

    # If the given library is used as archive parent library, it also shouldn't
    # be seen as a physical file to copy.
    #
    # I (Sybren) _think_ this is correct, but I'm not 100% sure. A test with an
    # embedded node tree produced a library data-block that's the 'archive
    # parent' one, and that didn't exist on disk.
    return any(
        otherlib.archive_parent_library == lib for otherlib in bpy.data.libraries
    )


def cache_clear() -> None:
    """Clear runtime caches used by this module.

    This should be called every time a new blend file is loaded.
    """
    library_abspath.cache_clear()
    library_is_archive.cache_clear()


@contextlib.contextmanager
def cache_autoclear() -> Generator[None, None, None]:
    """Automatically clear the runtime cache when the context exits."""
    try:
        yield
    finally:
        cache_clear()


def determine_rewriting_needs(repo: FileDependencyRepository) -> None:
    """Determine while file needs path rewriting.

    Sets file_info.needs_path_rewriting=True and file_info.rewrite_rules on all
    files that reference a relocated file.
    """

    libraries_needing_rewriting: set[BlendFile] = set()

    # Step 1: find all libraries that need rewriting.
    for file_info in repo.file_infoes.values():
        if file_info.needs_relocation:
            libraries_needing_rewriting |= file_info.references

    # Step 2: find the file_info instances for those libraries, and mark them.
    for library in libraries_needing_rewriting:
        abs_path = library_abspath(library)
        file_info = repo.file_infoes[abs_path]
        file_info.needs_path_rewriting = True

    # Step 3: determine the rewrite rules.
    for file_abs_path, file_info in repo.file_infoes.items():
        assert file_info.relpath_in_pack is not None, (
            "by now all paths in the pack should be known"
        )

        if not file_info.needs_relocation:
            continue

        # This file needs relocation, and thus all blendfiles that
        # refer to it need rewriting.

        for blendfile in file_info.references:
            blendfile_path = library_abspath(blendfile)
            blendfile_info = repo.file_infoes[blendfile_path]
            # Sanity check:
            assert blendfile_info.needs_path_rewriting, (
                f"should have marked {blendfile_path}"
            )
            blendfile_info.rewrite_rules[file_abs_path] = file_info.relpath_in_pack
