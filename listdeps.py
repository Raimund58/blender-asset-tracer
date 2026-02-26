# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
To run:

Assume the opened blend file sits in the project root:

$ blender -b tests/blendfiles/root/scene.blend -P file_path_visit.py

Explicitly provide a root path:

$ blender -b tests/blendfiles/root/scene.blend -P file_path_visit.py -- -r /some/other/root

"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any

try:
    import bpy  # pyright: ignore[reportMissingImports]
except ImportError:
    print(f"Run as: blender -b file/to/pack.blend -P {Path(__file__).name}")
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
    # show_file_references(cli_args.root_path)
    # print()
    listdeps(cli_args.root_path)
    _footer()


def show_file_references(root_path: Path) -> None:
    _header(f"Listing file paths relative to \033[95m{root_path}\033[0m:")

    def visit_path_fn(owner_id: bpy.types.ID, path: str, _: Any) -> str | None:
        abspath = file_usage.path_absolute(path, library=owner_id.library)

        try:
            printpath = abspath.relative_to(root_path)
            needs_relocation = False
        except ValueError:
            printpath = abspath
            needs_relocation = True

        if owner_id.library:
            lib = owner_id.library.filepath
        else:
            lib = "(local)"

        print(
            f"  {owner_id.id_type:10} id={_elide(owner_id.name, 30):30} lib={_elide(lib, 40):<40}",
            end="",
        )

        if abspath.exists():
            print(f"\033[{96 if needs_relocation else 92}m{printpath}\033[0m")
        else:
            print(f"\033[91m{printpath}\033[0m")

        return None

    bpy.data.file_path_foreach(visit_path_fn)


def listdeps(root_path: Path) -> None:
    # Investigate the blend file, and figure out the dependencies.
    with file_usage.cache_autoclear():
        deps_repo = file_usage.dependencies_of_current_blendfile(root_path)
        file_usage.determine_pack_paths_clustered(deps_repo)
        file_usage.determine_rewriting_needs(deps_repo)

    # Present the info to the terminal.
    print_all_files(deps_repo, root_path)
    print_relocation_rewriting_needs(deps_repo)
    print_rewrite_rules(deps_repo)


def print_all_files(
    deps_repo: file_usage.FileDependencyRepository, root_path: Path
) -> None:
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
    deps_repo: file_usage.FileDependencyRepository,
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


def print_rewrite_rules(deps_repo: file_usage.FileDependencyRepository) -> None:
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


@dataclasses.dataclass
class CLIArgs:
    root_path: Path


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
    parser.add_argument("-j", "--json", action="store_true", default=False)
    args = parser.parse_args(argv)

    return CLIArgs(root_path=file_usage.path_absolute(args.root))


if __name__ == "__main__":
    main(_parse_cli_args())
