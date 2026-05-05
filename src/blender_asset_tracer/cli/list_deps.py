# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# ***** END GPL LICENCE BLOCK *****
#
# (c) 2018, Blender Foundation - Sybren A. Stüvel
"""List dependencies of a blend file.

The paths are listed relative to the root directory (see --root). When files
are not contained in the root directory, they are listed by their absolute
path.
"""

import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

# The 'argparse' module doesn't nicely expose its types.
type ArgSubParser = Any
type CLIArguments = Any

if TYPE_CHECKING:
    from ..file_usage import FileDependencyRepository as _FileDependencyRepository
else:
    _FileDependencyRepository = object


def add_parser(subparsers: ArgSubParser) -> None:
    """Add argparser for this subcommand."""

    parser = subparsers.add_parser("list", help=__doc__)
    parser.set_defaults(func=cli_list)
    parser.add_argument("blendfile", type=Path)
    parser.add_argument(
        "-p",
        "--project",
        type=Path,
        default=None,
        help="Root directory of the project. If not given, the blend file is assumed to be at the root.",
    )
    parser.add_argument(
        "--flat",
        "-f",
        action="store_true",
        help="Show the files as a flat list. Without this option, each file has a list of its dependencies.",
    )
    parser.add_argument(
        "--sha256",
        "-s",
        action="store_true",
        help="Include SHA256sums in the output. Note that those may differ from the "
        "SHA256sums in a BAT-pack when paths are rewritten.",
    )
    parser.add_argument(
        "-t",
        "--timing",
        action="store_true",
        help="Include timing information in the output",
    )


def cli_list(args: CLIArguments) -> int:
    import bpy

    from .. import file_usage

    # Convert the CLI arguments to typed variables.
    blendfile: Path = args.blendfile
    root_path: Path = (
        args.project.resolve() if args.project else args.blendfile.resolve().parent
    )
    include_sha256: bool = args.sha256
    show_timing: bool = args.timing
    show_flat: bool = args.flat

    if not blendfile.exists():
        log.error("File %s does not exist", args.blendfile)
        return 3

    start_time = time.monotonic()

    bpy.ops.wm.open_mainfile(filepath=str(blendfile))
    deps_repo = file_usage.dependencies_of_current_blendfile(root_path)

    # Just print in SHA256sum format:
    time_spent_on_shasums = 0.0
    if include_sha256:
        time_spent_on_shasums = _print_sha256sums(deps_repo)
    elif show_flat:
        _print_file_flat(deps_repo)
    else:
        _print_file_tree(deps_repo)

    if show_timing:
        duration = time.monotonic() - start_time
        print("Spent %.2f seconds on producing this listing" % duration)
        if include_sha256:
            print("Spent %.2f seconds on calculating SHA sums" % time_spent_on_shasums)
            percentage = time_spent_on_shasums / duration * 100
            print("  (that is %d%% of the total time" % percentage)

    return 0


def _print_sha256sums(deps_repo: _FileDependencyRepository) -> float:
    """Show paths just like sha256sum would do.

    Paths are shown relative to the pack root. Except when not in the pack
    root, then paths are shown as absolute paths.
    """
    from .. import hashing

    time_spent_on_shasums = 0.0
    hasher = hashing.get_hasher()
    root_path = deps_repo.root_path

    for abs_path in sorted(deps_repo.file_infoes):
        hash_start_time = time.monotonic()
        try:
            shasum = hasher(abs_path)
        except FileNotFoundError:
            shasum = "-not found-"

        time_spent_on_shasums += time.monotonic() - hash_start_time
        print(shasum, end=" ")
        if abs_path.is_relative_to(root_path):
            print(abs_path.relative_to(root_path))
        else:
            print(abs_path)

    return time_spent_on_shasums


def _print_file_tree(deps_repo: _FileDependencyRepository) -> None:
    from ..file_usage import FileInfo, PathType, library_abspath

    # Build a map of file references.
    # Maps 'user file' to 'used file'.
    dependencies: dict[Path, dict[Path, PathType]] = defaultdict(dict)
    for used_file_info in deps_repo.file_infoes.values():
        used_file_path = used_file_info.source_path
        # Go over all incoming references to see what uses this file.
        for user_lib, path_type in used_file_info.references.items():
            user_file_path = library_abspath(user_lib)
            dependencies[user_file_path][used_file_path] = path_type

    root_path = deps_repo.root_path

    def _print_path(path: Path) -> Path:
        if path.is_relative_to(root_path):
            return path.relative_to(root_path)
        return path

    def _print(user_file_info: FileInfo) -> None:
        user_file_path = user_file_info.source_path
        used_paths = dependencies[user_file_path]

        print(_print_path(user_file_path))
        for lib_path in sorted(used_paths):
            print(f"    {_print_path(lib_path)}")

    # Start with the source input file.
    source_file_info = deps_repo.source_file_info()
    _print(source_file_info)
    del deps_repo.file_infoes[source_file_info.source_path]

    # Go over the rest of the files in sorted order. Only print files
    # that themselves reference other files (i.e. linked .blend files
    # that have outgoing dependencies). Leaf assets (images, fonts, ...)
    # were already printed nested under the file that uses them, so
    # listing them again as standalone top-level entries would be a
    # confusing duplication.
    for abs_path in sorted(deps_repo.file_infoes):
        file_info = deps_repo.file_infoes[abs_path]
        if not dependencies.get(file_info.source_path):
            continue
        _print(file_info)


def _print_file_flat(deps_repo: _FileDependencyRepository) -> None:
    root_path = deps_repo.root_path

    def _print_path(path: Path) -> Path:
        if path.is_relative_to(root_path):
            return path.relative_to(root_path)
        return path

    # Start with the source input file.
    print(_print_path(deps_repo.packed_source_file))
    del deps_repo.file_infoes[deps_repo.packed_source_file]

    # Go over the rest of the files in sorted order.
    for abs_path in sorted(deps_repo.file_infoes):
        print(_print_path(abs_path))
