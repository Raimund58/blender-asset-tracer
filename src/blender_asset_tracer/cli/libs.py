# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
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

    parser = subparsers.add_parser("libs", help=__doc__)
    parser.set_defaults(func=cli_libs)
    parser.add_argument("blendfile", type=Path)
    parser.add_argument(
        "-r",
        "--root",
        type=Path,
        default=None,
        help="Root directory of the project. If not given, the blend file is assumed to be at the root.",
    )


def cli_libs(args: CLIArguments) -> int:
    import bpy

    from .. import file_usage

    # Convert the CLI arguments to typed variables.
    blendfile: Path = args.blendfile
    root_path: Path = (
        args.root.resolve() if args.root else args.blendfile.resolve().parent
    )

    if not blendfile.exists():
        log.error("File %s does not exist", args.blendfile)
        return 3

    bpy.ops.wm.open_mainfile(filepath=str(blendfile))
    deps_repo = file_usage.dependencies_of_current_blendfile(root_path)

    _print_file_tree(deps_repo)

    return 0


def _print_file_tree(deps_repo: _FileDependencyRepository) -> None:
    from ..file_usage import FileInfo, library_abspath

    # Build a map of file references, but only for blend files.
    # Maps 'user file' to 'used file'.
    dependencies: dict[Path, set[Path]] = defaultdict(set)
    for used_file_info in deps_repo.file_infoes.values():
        used_file_path = used_file_info.source_path
        if used_file_path.suffix.lower() != ".blend":
            continue

        # Go over all incoming references to see what uses this file.
        for user_lib in used_file_info.references:
            user_file_path = library_abspath(user_lib)
            dependencies[user_file_path].add(used_file_path)

    root_path = deps_repo.root_path

    def _print_path(path: Path) -> Path:
        if path.is_relative_to(root_path):
            return path.relative_to(root_path)
        return path

    def _print(user_file_info: FileInfo) -> None:
        user_file_path = user_file_info.source_path
        used_paths = dependencies[user_file_path]

        # Internally the main blend file depends on itself, but that doesn't
        # need to be shown here.
        used_paths.discard(user_file_path)

        print(_print_path(user_file_path))
        for lib_path in sorted(used_paths):
            print(f"    {_print_path(lib_path)}")

    # Start with the source input file.
    source_file_info = deps_repo.source_file_info()
    _print(source_file_info)
    del deps_repo.file_infoes[source_file_info.source_path]

    # Go over the rest of the files in sorted order.
    for abs_path in sorted(deps_repo.file_infoes):
        if abs_path not in dependencies:
            # This was not a blend file.
            continue

        file_info = deps_repo.file_infoes[abs_path]
        if not file_info.references:
            continue
        _print(file_info)
