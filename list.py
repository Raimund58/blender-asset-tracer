# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
To run:

$ blender -q -b tests/blendfiles/root/scene.blend -P list.py
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

try:
    import bpy  # pyright: ignore[reportMissingImports]
except ImportError:
    print(f"Run as: blender -q -b file.blend -P {Path(__file__).name}")
    raise SystemExit(1)

# Ensure BAT can be imported, even when it's not installed as package.
_my_dir = Path(__file__).absolute().parent
if str(_my_dir) not in sys.path:
    sys.path.append(str(_my_dir))


from blender_asset_tracer import file_usage

ANSI_REWRITING = 37
ANSI_RELOCATING = 93
ANSI_BOTH = 95
ANSI_PLAIN = 90


def main(cli_args: CLIArgs) -> None:
    deps_repo = file_usage.dependencies_of_current_blendfile(cli_args.root_path)

    cwd = Path().resolve()
    for abs_path in sorted(deps_repo.file_infoes):
        if abs_path.is_relative_to(cwd):
            print_path = abs_path.relative_to(cwd)
        else:
            print_path = abs_path
        print(print_path)


@dataclasses.dataclass
class CLIArgs:
    root_path: Path


def _parse_cli_args() -> CLIArgs:
    import argparse
    import sys

    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1 :]
    else:
        argv = []

    current_blendfile_path = file_usage.path_absolute(bpy.data.filepath)
    current_blendfile_dir = current_blendfile_path.parent

    my_name = Path(__file__).name
    parser = argparse.ArgumentParser(my_name)
    parser.add_argument("-r", "--root", type=Path, default=current_blendfile_dir)
    args = parser.parse_args(argv)

    return CLIArgs(root_path=file_usage.path_absolute(args.root))


if __name__ == "__main__":
    main(_parse_cli_args())
