# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import contextlib
import dataclasses
import enum
import fnmatch
import functools
import os.path
from collections.abc import Generator, Iterable
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

    # This is the root directory for files that need relocation (i.e. files that
    # reside outside the project root) The path is relative to the pack root.
    relocated_root: PurePath = PurePath("_outside_project")

    # Globs on filenames that should be ignored by BAT.
    #
    # Matching is only done on the filename itself, not the full path.
    #
    # Can be used to exclude things like Alembic files ('*.abc') or legacy
    # particle system caches ('*.bphys').
    ignore_globs: set[str] = dataclasses.field(default_factory=set)


class PathType(enum.Enum):
    """Records the path type by which file A uses file B.

    The numerical values of the enum items are in order of dominance. If
    there's multiple ways in which A uses B (for example, a scratch texture
    used by various materials), the most dominant type wins.
    """

    # Relative path. Unless it references a file outside the project root,
    # no rewriting is necessary.
    RELATIVE = 0

    # Uknown path. Linking between blend files doesn't allow introspection of
    # which blend file is using which exact path to refer to its libraries.
    UNKNOWN = 1

    # Absolute path. These always need to be rewritten, because the BAT pack is
    # going to be at a different absolute path.
    ABSOLUTE = 2

    @classmethod
    def for_bpath(cls, blender_path: str) -> PathType:
        """Return the path type for the given Blender path."""
        if blender_path[:2] == "//":
            return cls.RELATIVE
        return cls.ABSOLUTE


@dataclasses.dataclass
class FileInfo:
    # The absolute path of the file described by this FileInfo.
    #
    # This is also used as the key in FileDependencyRepository.file_infoes. The
    # advantage of also storing it here, is that an instance of FileInfo is then
    # enough to know all the relevant info about this file.
    source_path: Path

    # The path that Blender reported. If this is None, it's the same as
    # `source_path`.
    #
    # This is only set when Blender reports a single path that actually is a
    # placeholder for multiple files (like UDIM paths).
    reported_path: Path | None = None

    # Indicator that this file needs relocation.
    #
    # `relpath_in_pack` is only allowed to be None if this is True.
    #
    # Even after `relpath_in_pack` is determined for relocated files, this field
    # can remain set to True.
    #
    # The only reason it will be reset to False is when the file does not
    # actually exist on disk (because then there is nothing to relocate). This
    # prevents the path rewriting of files that only refer to missing files.
    needs_relocation: bool = False

    # Indicator that this file needs path rewriting.
    #
    # This means that this file referenced a file that has
    # `needs_relocation=True`, or it references a dependency by absolute path
    # (which has to be turned into a relative path). Or both.
    needs_path_rewriting: bool = False

    # The path, relative to the project root, where this file will sit on the
    # farm. For to-be-relocated paths, this is initially None, as determining
    # that requires a more global view of all files that need relocating.
    relpath_in_pack: PurePath | None = None

    # Library files that contain data-blocks that reference this file.
    #
    # Absolute paths are 'dominant': if there are multiple references, and one
    # of them was with an absolute path, the absolute path 'wins' and determines
    # the value in the dictionary.
    references: dict[BlendFile, PathType] = dataclasses.field(default_factory=dict)

    # Rewrite rules that should be applied to this file.
    # Should only be set when `needs_path_rewriting=True`.
    rewrite_rules: RewriteRules = dataclasses.field(default_factory=dict)

    # Absolute path of the file's location after it had its paths rewritten.
    rewritten_file_path: Path | None = None

    @property
    def path_to_pack(self) -> Path:
        """Return the file to include in the BAT pack.

        If the file needed path rewriting, this is the path of the rewritten
        file. Otherwise this is just the source file.
        """
        return self.rewritten_file_path or self.source_path

    def add_reference(self, blendfile: BlendFile, path_type: PathType) -> None:
        # Whether the new path type overwrites the existing path type depends on
        # the existing path type.
        existing_type = self.references.get(blendfile, None)
        match existing_type:
            case PathType.ABSOLUTE:
                # ABSOLUTE is the dominant type, because use of an absolute path
                # means the user has to be rewritten to use a relative path.
                return
            case PathType.UNKNOWN:
                match path_type:
                    # Only ABSOLUTE gets to overwrite UNKNOWN.
                    case PathType.ABSOLUTE:
                        self.references[blendfile] = path_type
                    case _:
                        return
            case PathType.RELATIVE:
                self.references[blendfile] = path_type
            case None:
                self.references[blendfile] = path_type


@dataclasses.dataclass
class FileDependencyRepository:
    """Collection of FileInfo objects for each file."""

    # The absolute root path of the project. This is used to determine whether
    # relocation is needed or not.
    root_path: Path

    # Absolute path of the blend file this entire FileDependencyRepository was
    # created for. This can be used to look up its info in file_infoes.
    packed_source_file: Path = Path()

    # Mapping from absolute path to FileInfo.
    file_infoes: dict[Path, FileInfo] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        assert self.root_path.is_absolute()

    def source_file_info(self) -> FileInfo:
        """Get the FileInfo for the currently-open blend file."""
        try:
            return self.file_infoes[self.packed_source_file]
        except KeyError:
            print("Cannot find source file info")
            print(f"Source file: {self.packed_source_file}")
            if self.file_infoes:
                print("Available files:")
                for path in self.file_infoes.keys():
                    print(f"    - {path}")
            else:
                print("NO files known! This is weird, indeed.")
            raise


def _deps_repo_add_path(
    deps_repo: FileDependencyRepository,
    reported_path: Path,
    *,
    used_by_library: BlendFile,
    path_type: PathType,
) -> None:
    """Add a file to the repository.

    :param abspath: Absolute path of the file. This can be an external asset
       (like a `.png`) or a `.blend` file.
    :param used_by_library: the Library data-block (or None, if the current
       blend file) that uses this file.
    """

    # Handle directory paths. Only paths that exist can be checked for 'directoryness'.
    if reported_path.is_dir():
        for file_path in reported_path.rglob("*", recurse_symlinks=True):
            if file_path.is_dir():
                # The rglob() should already go in there and iterate over the
                # files too, so we can just skip directories here.
                continue

            _deps_repo_add_file_single(
                deps_repo,
                abspath=file_path,
                reported_path=None,
                used_by_library=used_by_library,
                path_type=path_type,
            )
        return

    # Detect file paths that actually represent multiple files.
    #
    # NOTE: this only supports globbing in the filename part of the path. If
    # more is required, the code needs some work.
    if "<UDIM>" in reported_path.name:
        glob_path = reported_path.with_name(reported_path.name.replace("<UDIM>", "*"))
    else:
        # No globbing necessary.
        _deps_repo_add_file_single(
            deps_repo,
            abspath=reported_path,
            reported_path=None,
            used_by_library=used_by_library,
            path_type=path_type,
        )
        return

    # Use case-insensitive globbing, as the path may come from Windows while
    # running on Linux.
    for abs_path in glob_path.parent.rglob(
        glob_path.name, case_sensitive=False, recurse_symlinks=True
    ):
        if not abs_path.is_file(follow_symlinks=True):
            # Directories themselves cannot be packed, only files.
            # And UNIX sockets should also be skipped.
            continue
        _deps_repo_add_file_single(
            deps_repo,
            abspath=abs_path,
            reported_path=reported_path,
            used_by_library=used_by_library,
            path_type=path_type,
        )


def _deps_repo_add_file_single(
    deps_repo: FileDependencyRepository,
    *,
    abspath: Path,
    reported_path: Path | None,
    used_by_library: BlendFile,
    path_type: PathType,
) -> FileInfo:
    if abspath.exists():
        assert abspath.is_file(), f"{abspath} is not a file"

    try:
        file_info = deps_repo.file_infoes[abspath]
    except KeyError:
        pass
    else:
        # Remember that this library blend file references this asset file.
        file_info.add_reference(used_by_library, path_type)
        return file_info

    # Construct all the file info. Most of this code just depends on the
    # file's path and the root path, which means it doesn't have to be
    # repeated for every ID that uses it.
    file_info = FileInfo(
        source_path=abspath,
        reported_path=reported_path,
    )
    deps_repo.file_infoes[abspath] = file_info

    # Remember that this library blend file references this asset file.
    file_info.add_reference(used_by_library, path_type)

    try:
        relpath_in_pack = PurePath(abspath.relative_to(deps_repo.root_path))
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
        determine_pack_paths_clustered(deps_repo, options)
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
    source_file = library_abspath(None)
    deps_repo.packed_source_file = source_file
    _deps_repo_add_path(
        deps_repo, source_file, used_by_library=None, path_type=PathType.RELATIVE
    )

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

            _deps_repo_add_path(
                deps_repo,
                used_lib_path,
                used_by_library=id_user.library,
                path_type=PathType.UNKNOWN,
            )

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

        path_type = PathType.for_bpath(path)
        abspath = path_absolute(path, library=owner_id.library)
        _deps_repo_add_path(
            deps_repo, abspath, used_by_library=owner_id.library, path_type=path_type
        )
        return None

    bpy.data.file_path_foreach(_visit_path_usage)

    # Step 3: remove all entries that should be ignored. This is easier to do as
    # a post-process than to weave all the 'ignore' options into the code above.
    if options.ignore_globs:
        # Ensure the globs are all lower-case, as the comparison should be done
        # case-insensitively.
        globs = [glob.lower() for glob in options.ignore_globs]
        to_remove = {
            path
            for path in deps_repo.file_infoes.keys()
            if _filename_matches_any_glob(path.name.lower(), globs)
        }
        for path in to_remove:
            del deps_repo.file_infoes[path]


def _filename_matches_any_glob(file_name: str, globs: Iterable[str]) -> bool:
    """Return whether the filename matches any of the globs.

    Comparison is done case-sensitively regardless of OS. The caller should
    transform the file name and the globs to lower case if case-insensitive
    comparisons are needed.
    """
    return any(fnmatch.fnmatchcase(file_name, glob) for glob in globs)


def determine_pack_paths_clustered(
    repo: FileDependencyRepository,
    options: Options = Options(),
) -> None:
    """Update all the files in the repository so they know their path in the pack.

    Sets file_info.relpath_in_pack for each file in repo.file_infoes.

    This determines clusters of out-of-project paths, so that each cluster can
    be stored in as short a path as possible.
    """

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

    relocated_root = options.relocated_root
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


def determine_pack_paths_simple(
    repo: FileDependencyRepository,
    options: Options = Options(),
) -> None:
    """Update all the files in the repository so they know their path in the pack.

    Sets file_info.relpath_in_pack for each file in repo.file_infoes.

    This simply puts the files into "./_outside_project/{absolute path}".
    """

    relocated_root = options.relocated_root
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


@functools.lru_cache(maxsize=1024)
def library_abspath(lib: BlendFile | None) -> Path:
    """Return the absolute path to the library.

    lib=None returns the absolute path of the current blend file.
    """
    if lib is None:
        assert bpy.data.filepath, "no blend file is loaded"
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


@functools.lru_cache(maxsize=1024)
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
        if not file_info.needs_relocation:
            continue

        # Check whether the file actually exists on disk. There is no need to do
        # path rewriting when a file doesn't exist anyway. This _could_ be seen
        # as security issue, as referencing a missing file could make Blender
        # load an out-of-project file on the farm. However, the
        # Options(use_relative_only=True) option already makes that possible.
        if not file_info.source_path.exists():
            assert file_info.relpath_in_pack is not None, (
                "This code should only be executed once relpack_in_pack is determined"
            )
            file_info.needs_relocation = False
            continue

        libraries_needing_rewriting |= set(file_info.references)

    # Step 2: find the file_info instances for those libraries, and mark them.
    for library in libraries_needing_rewriting:
        abs_path = library_abspath(library)
        assert abs_path is not None
        assert abs_path is not Path()

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

            # Store rewrite rules per directory. This ensures that 'fake' file
            # paths (like with the '<UDIM>' markers) get mapped correctly too.
            assert file_abs_path.name == file_info.relpath_in_pack.name, (
                f"path rewriting should retain the filename: {file_abs_path} - {file_info.relpath_in_pack}"
            )
            blendfile_info.rewrite_rules[file_abs_path.parent] = (
                file_info.relpath_in_pack.parent
            )
