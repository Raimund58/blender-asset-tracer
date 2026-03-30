# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..file_usage import FileDependencyRepository as _FileDependencyRepository
else:
    _FileDependencyRepository = object


ANSI_REWRITING = 37
ANSI_RELOCATING = 93
ANSI_BOTH = 95
ANSI_PLAIN = 90

log = logging.getLogger(__name__)

# The 'argparse' module doesn't nicely expose its types.
type ArgSubParser = Any
type CLIArguments = Any


def add_parser(subparsers: ArgSubParser) -> None:
    """Add argparser for this subcommand."""

    parser = subparsers.add_parser("debug", help=__doc__)
    parser.set_defaults(func=cli_debug)
    parser.add_argument("blendfile", type=Path)
    parser.add_argument(
        "-p",
        "--project",
        type=Path,
        default=None,
        help="Root directory of the project. If not given, the blend file is assumed to be at the root.",
    )


def cli_debug(args: CLIArguments) -> int:
    import bpy  # pyright: ignore[reportMissingImports]

    from .. import file_usage

    # Convert the CLI arguments to typed variables.
    blendfile: Path = args.blendfile
    root_path: Path = (
        args.project.resolve() if args.project else args.blendfile.resolve().parent
    )

    if not blendfile.exists():
        log.error("File %s does not exist", args.blendfile)
        return 3

    bpy.ops.wm.open_mainfile(filepath=str(blendfile))
    deps_repo = file_usage.dependencies_of_current_blendfile(root_path)

    # Present the info to the terminal.
    print_all_files(deps_repo, root_path)
    print_relocation_rewriting_needs(deps_repo)
    print_rewrite_rules(deps_repo)

    return 0


def print_all_files(deps_repo: _FileDependencyRepository, root_path: Path) -> None:
    from .. import file_usage

    _header(f"All files (paths relative to \033[95m{root_path}\033[0m)")

    for abs_path, info in deps_repo.file_infoes.items():
        color = 92 if info.relpath_in_pack else 95
        relpath = str(abs_path.relative_to(root_path, walk_up=True))
        in_pack = str(info.relpath_in_pack or "?")

        if info.needs_relocation:
            in_pack_color = ANSI_RELOCATING
        elif info.relpath_in_pack:
            in_pack_color = ANSI_PLAIN
        else:
            # Conflict: needs_relocation is False, but relpath_in_pack is not set either.
            in_pack_color = 91

        print(f"\033[{color}m{relpath}\033[0m:")
        print(f"    in_pack = \033[{in_pack_color}m{in_pack}\033[0m")
        for ref in info.references:
            ref_path = file_usage.library_abspath(ref).relative_to(
                root_path, walk_up=True
            )
            print(f"    ref by  = {ref_path if ref else '(local)'}")


def print_relocation_rewriting_needs(
    deps_repo: _FileDependencyRepository,
) -> None:
    _header(
        f"Blend files needing "
        f"\033[{ANSI_REWRITING}mrewriting\033[0m, "
        f"\033[{ANSI_RELOCATING}mrelocating\033[0m, "
        f"\033[{ANSI_BOTH}mboth\033[0m, or "
        f"\033[{ANSI_PLAIN}mnothing\033[0m:"
    )
    for abs_path, file_info in deps_repo.file_infoes.items():
        if file_info.needs_path_rewriting and file_info.needs_relocation:
            colour = ANSI_BOTH
        elif file_info.needs_path_rewriting:
            colour = ANSI_REWRITING
        elif file_info.needs_relocation:
            colour = ANSI_RELOCATING
        else:
            colour = ANSI_PLAIN
        print(f"  - \033[{colour}m{abs_path}\033[0m")


def print_rewrite_rules(deps_repo: _FileDependencyRepository) -> None:
    shown_header = False
    for abs_path, file_info in deps_repo.file_infoes.items():
        if not file_info.needs_path_rewriting:
            continue

        if not shown_header:
            _header("Rewrite rules:")
            shown_header = True

        print(f"- \033[{ANSI_REWRITING}m{abs_path}\033[0m")
        for from_path, to_path in file_info.rewrite_rules.items():
            print(f"    - \033[{ANSI_RELOCATING}m{from_path}\033[0m")
            print(f"      {to_path}")


def _header(string: str) -> None:
    _line()
    print(string)
    _line()


def _footer() -> None:
    _line()


def _line() -> None:
    print(100 * "=")


def _elide(string: Any, maxlen: int) -> str:
    if not isinstance(string, str):
        string = str(string)
    assert isinstance(string, str)  # Because mypy is a bit stoopid.

    if len(string) <= maxlen:
        return string

    dotdotdot = "…"
    half = (maxlen - len(dotdotdot)) // 2
    return f"{string[:half]}{dotdotdot}{string[-half:]}"
