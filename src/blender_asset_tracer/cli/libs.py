# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

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

    parser = subparsers.add_parser("libs", help=__doc__)
    parser.set_defaults(func=cli_libs)
    parser.add_argument("blendfile", type=Path)


def cli_libs(args: CLIArguments) -> int:
    import bpy

    # Convert the CLI arguments to typed variables.
    blendfile: Path = args.blendfile

    if not blendfile.exists():
        log.error("File %s does not exist", args.blendfile)
        return 3

    print(f"Loading {args.blendfile}")
    with bpy.data.libraries.load(str(args.blendfile), link=True) as (data, _):
        for key in dir(data):
            collection = getattr(data, key)
            print(f"data.{key}:")
            for name in collection:
                print(f"    - {name}")

    return 0
