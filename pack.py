# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
To test:

Assumes the current working directory is the project root:

$ blender -q -b tests/blendfiles/root/scene.blend -P pack.py -- target/directory

Explicitly provide a root path:

$ blender -q -b tests/blendfiles/root/scene.blend -P pack.py -- -r /some/other/root target/directory

"""

import argparse
import dataclasses
import os
import shutil
import sys
from pathlib import Path, PurePath
from typing import Any

# Ensure BAT can be imported, even when it's not installed as package.
_my_dir = Path(__file__).resolve().parent
if str(_my_dir) not in sys.path:
    sys.path.append(str(_my_dir))

# E402: Import not at top of file, but has to be below the modification sys.path.
from blender_asset_tracer import file_usage, path_rewriting  # noqa: E402
from blender_asset_tracer.path_rewriting_process import (
    BackgroundRewriter,
    RewriteRequest,
)


@dataclasses.dataclass
class CLIArgs:
    root_path: Path
    target_path: Path
    use_relative_only: bool


def main() -> None:
    cli_args = parse_cli_args()
    root_path = cli_args.root_path

    header = f"Packing, relative to \033[38;5;214m{root_path}\033[0m → {cli_args.target_path}"
    separator = (len(header) - 15) * "-"  #  remove ANSI control codes
    print(separator)
    print(header)
    print(separator)

    options = file_usage.Options(
        use_relative_only=cli_args.use_relative_only,
    )

    # Investigate the blend file, and figure out the dependencies.
    deps_repo = file_usage.dependencies_of_current_blendfile(root_path, options)

    errors = perform_path_rewriting(deps_repo)

    if errors:
        print(separator)
        print("Errors while packing:")
        for abs_path in sorted(errors):
            errormsg = errors[abs_path]
            print(f"  {abs_path}:")
            print(f"      {errormsg}")
        raise SystemExit(2)

    create_pack(deps_repo, cli_args.target_path)

    # Find the entry point of the pack.
    source_abs_path = file_usage.library_abspath(None)
    pack_entry_point = deps_repo.file_infoes[source_abs_path].relpath_in_pack
    assert pack_entry_point is not None
    create_pack_description(cli_args.target_path, pack_entry_point)

    print(separator)


def perform_path_rewriting(
    deps_repo: file_usage.FileDependencyRepository,
) -> dict[Path, str]:
    """Perform path rewriting on all files that need it.

    Return a dict {abs_path: error message} for each blend file for which the
    path rewriting failed.
    """

    # Only start the background process if there are actually files to rewrite.
    blendfiles_to_rewrite = path_rewriting.determine_files_to_rewrite(deps_repo)
    if not blendfiles_to_rewrite:
        return {}

    # Keep track of failures reported via the callbacks below.
    failures: dict[Path, str] = {}

    def on_rewrite_done(request: RewriteRequest) -> None:
        print(f"\033[92mRewrite done: {request=}\033[0m")

    def on_rewrite_error(request: RewriteRequest, errormsg: str) -> None:
        failures[request.blendfile] = errormsg
        print(f"\033[91mRewrite done: {request=}  {errormsg=}\033[0m")

    def on_callback_error(
        request: RewriteRequest,
        ex: Exception,
        callback: BackgroundRewriter.RewriteCallback,
        callback_args: tuple[Any, ...],
    ) -> None:
        # This error means the on_rewrite_done() callback itself caused an exception. That's a bug.
        raise RuntimeError(
            f"Callback error: {request=}  {ex=} {callback=} {callback_args}"
        )

    bgrewriter = BackgroundRewriter(on_callback_error)
    bgrewriter.start()

    try:
        for abs_path in blendfiles_to_rewrite:
            file_info = deps_repo.file_infoes[abs_path]

            # Skip files that don't need rewriting.
            if not file_info.needs_path_rewriting:
                continue

            # Only perform path rewriting when the file actually exists. It's
            # definitely possible for a blend file to refer to missing files.
            if not abs_path.exists():
                print(f"\033[38;5;214mSkipping: {abs_path} does not exist\033[0m")
                continue

            # Sanity check.
            assert file_info.relpath_in_pack is not None, (
                f"by now relpath_in_pack should be known for every file: {abs_path}"
            )
            assert file_info.rewritten_file_path is not None, (
                f"by now rewritten_file_path should be known for every file: {abs_path}"
            )

            bgrewriter.queue_rewrite(
                abs_path,
                file_info.relpath_in_pack,
                file_info.rewrite_rules,
                file_info.rewritten_file_path,
                on_file_done=on_rewrite_done,
                on_file_error=on_rewrite_error,
            )
            print(
                f"\033[96mQueueing: {abs_path} → {file_info.rewritten_file_path}\033[0m"
            )

        print(
            "\033[96mAll rewrite operations queued, waiting for sub-process to be done.\033[0m"
        )

        while not bgrewriter.all_rewrites_done:
            bgrewriter.update()
    finally:
        bgrewriter.shutdown()

    return failures


def create_pack(
    deps_repo: file_usage.FileDependencyRepository, target_path: Path
) -> None:
    """Copy all files in the repository to the target path."""

    missing_files = 0

    for abs_path, file_info in deps_repo.file_infoes.items():
        # Maybe use the path-rewritten file?
        if file_info.needs_path_rewriting:
            assert file_info.rewritten_file_path is not None, (
                f"file needs path rewriting, but that hasn't happened yet: {abs_path}"
            )
            abs_path = file_info.rewritten_file_path

        # Sanity check.
        assert file_info.relpath_in_pack is not None, (
            f"the path in the pack should be known by know: {abs_path}"
        )

        # TODO: some file names actually should indicate a whole set of files.
        # This can be a `blabla<UDIM>.ext` name, but maybe there are other cases
        # as well. Needs investigation.

        # Skip missing files.
        if not abs_path.exists():
            print(f"MISSING: {abs_path}")
            missing_files += 1
            continue

        save_to = target_path / file_info.relpath_in_pack
        save_to.parent.mkdir(parents=True, exist_ok=True)

        # Actually do the copy.
        print(file_info.relpath_in_pack)
        shutil.copy2(abs_path, save_to)

    if missing_files:
        print(f"There were {missing_files} misisng files")


def create_pack_description(target_dir: Path, entry_point_of_pack: PurePath) -> None:
    info_file = target_dir / "pack-info.txt"
    with info_file.open("w") as outfile:
        print("This is a Blender Asset Tracer pack.", file=outfile)
        print("Start by opening the following blend file:", file=outfile)
        print(f"   {entry_point_of_pack.as_posix()}", file=outfile)


def parse_cli_args() -> CLIArgs:
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1 :]
    else:
        argv = []

    cwd = Path(os.getcwd())

    my_name = Path(__file__).name
    parser = argparse.ArgumentParser(f"blender -b <blendfile> -P {my_name} --")
    parser.add_argument("-r", "--root", type=Path, default=cwd)
    parser.add_argument("--relative-only", action="store_true", default=False)
    parser.add_argument("target", type=Path)
    args = parser.parse_args(argv)

    try:
        # Detect whether we're running inside Blender or not.
        import bpy  # pyright: ignore[reportMissingImports, reportUnusedImport]  # noqa: F401
    except ImportError:
        parser.print_usage()
        raise SystemExit(1)

    return CLIArgs(
        root_path=args.root.absolute(),
        target_path=args.target,
        use_relative_only=args.relative_only,
    )


if __name__ == "__main__":
    main()
