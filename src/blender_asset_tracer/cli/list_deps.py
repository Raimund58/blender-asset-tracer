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
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# The 'argparse' module doesn't nicely expose its types.
type ArgSubParser = Any
type CLIArguments = Any


def add_parser(subparsers: ArgSubParser) -> None:
    """Add argparser for this subcommand."""

    parser = subparsers.add_parser("list", help=__doc__)
    parser.set_defaults(func=cli_list)
    parser.add_argument("blendfile", type=Path)
    parser.add_argument(
        "-r",
        "--root",
        type=Path,
        default=None,
        help="Root directory of the project. If not given, the blend file is assumed to be at the root.",
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

    from .. import file_usage, hashing

    # Convert the CLI arguments to typed variables.
    blendfile: Path = args.blendfile
    root_path: Path = (
        args.root.resolve() if args.root else args.blendfile.resolve().parent
    )
    include_sha256: bool = args.sha256
    show_timing: bool = args.timing

    if not blendfile.exists():
        log.error("File %s does not exist", args.blendfile)
        return 3

    time_spent_on_shasums = 0.0
    start_time = time.monotonic()

    bpy.ops.wm.open_mainfile(filepath=str(blendfile))
    deps_repo = file_usage.dependencies_of_current_blendfile(root_path)

    hasher = hashing.get_hasher()

    # TODO: show as a dependency tree, instead of just a flat list of files.
    for abs_path in sorted(deps_repo.file_infoes):
        if abs_path.is_relative_to(root_path):
            print_path = abs_path.relative_to(root_path)
        else:
            print_path = abs_path

        if not include_sha256:
            print(print_path)
            continue

        hash_start_time = time.monotonic()
        try:
            shasum = hasher(abs_path)
        except FileNotFoundError:
            shasum = "-not found-"

        time_spent_on_shasums += time.monotonic() - hash_start_time
        print(print_path, shasum)

    if show_timing:
        duration = time.monotonic() - start_time
        print("Spent %.2f seconds on producing this listing" % duration)
        if include_sha256:
            print("Spent %.2f seconds on calculating SHA sums" % time_spent_on_shasums)
            percentage = time_spent_on_shasums / duration * 100
            print("  (that is %d%% of the total time" % percentage)

    return 0
