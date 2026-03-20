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
"""Create a BAT-pack for the given blend file."""

import dataclasses
import logging
import shutil
import sys
from pathlib import Path, PurePath
from typing import Any

from .. import file_usage, path_rewriting
from ..path_rewriting_models import RewriteRequest
from ..path_rewriting_process import BackgroundRewriter

# The 'argparse' module doesn't nicely expose its types.
type ArgSubParser = Any
type ParsedArgs = Any


@dataclasses.dataclass
class CLIArgs:
    blendfile: Path
    project_root_dir: Path
    target_path: Path
    exclude_globs: set[str]
    use_relative_only: bool


log = logging.getLogger(__name__)


def cli_pack(raw_args: ParsedArgs) -> int:
    import bpy

    cli_args = interpret_cli_args(raw_args)

    options = file_usage.Options(
        use_relative_only=cli_args.use_relative_only,
        ignore_globs=cli_args.exclude_globs,
    )

    # Load the blend file.
    bpy.ops.wm.open_mainfile(filepath=str(cli_args.blendfile))

    # Investigate the blend file, and figure out the dependencies.
    deps_repo = file_usage.dependencies_of_current_blendfile(
        cli_args.project_root_dir, options
    )

    errors = perform_path_rewriting(deps_repo)

    if errors:
        log.error("Errors while packing:")
        for abs_path in sorted(errors):
            errormsg = errors[abs_path]
            log.error(f"  {abs_path}:")
            log.error(f"      {errormsg}")
        return 2

    create_pack(deps_repo, cli_args.target_path)

    # Find the entry point of the pack.
    source_abs_path = file_usage.library_abspath(None)
    pack_entry_point = deps_repo.file_infoes[source_abs_path].relpath_in_pack
    assert pack_entry_point is not None
    create_pack_description(cli_args.target_path, pack_entry_point)

    return 0


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

    def on_rewrite_start(request: RewriteRequest) -> None:
        log.info(f"Rewriting: {request.blendfile}")

    def on_rewrite_done(request: RewriteRequest) -> None:
        log.debug(f"Rewrite done: {request=}")

    def on_rewrite_error(request: RewriteRequest, errormsg: str) -> None:
        failures[request.blendfile] = errormsg
        log.error(f"Rewrite error: {request.blendfile}  {errormsg=}")

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
                log.warning(f"Skipping: {abs_path} does not exist")
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
                on_file_start=on_rewrite_start,
                on_file_done=on_rewrite_done,
                on_file_error=on_rewrite_error,
            )
            log.info(f"Queueing: {abs_path} → {file_info.rewritten_file_path}")

        log.info("All rewrite operations queued, waiting for sub-process to be done.")

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

        # Skip missing files.
        if not abs_path.exists():
            log.error(f"MISSING: {abs_path}")
            missing_files += 1
            continue

        save_to = target_path / file_info.relpath_in_pack
        save_to.parent.mkdir(parents=True, exist_ok=True)

        # Actually do the copy.
        print(file_info.relpath_in_pack)
        shutil.copy2(abs_path, save_to)

    if missing_files:
        log.error(f"There were {missing_files} missing files")


def create_pack_description(target_dir: Path, entry_point_of_pack: PurePath) -> None:
    info_file = target_dir / "pack-info.txt"
    with info_file.open("w") as outfile:
        print("This is a Blender Asset Tracer pack.", file=outfile)
        print("Start by opening the following blend file:", file=outfile)
        print(f"   {entry_point_of_pack.as_posix()}", file=outfile)


def add_parser(subparsers: ArgSubParser) -> None:
    """Add argparser for this subcommand."""

    parser = subparsers.add_parser("pack", help=__doc__)
    parser.set_defaults(func=cli_pack)
    parser.add_argument("blendfile", type=Path, help="The Blend file to pack.")
    parser.add_argument(
        "target",
        type=Path,
        help="Directory where to create the pack.",
    )
    parser.add_argument(
        "-p",
        "--project",
        type=Path,
        help="Root directory of your project. Paths to below this directory are "
        "kept in the BAT Pack as well, whereas references to assets from "
        "outside this directory will have to be rewitten. The blend file MUST "
        "be inside the project directory. If this option is ommitted, the "
        "directory containing the blend file is taken as the project "
        "directoy.",
    )
    # parser.add_argument(
    #     "-n",
    #     "--noop",
    #     default=False,
    #     action="store_true",
    #     help="Don't copy files, just show what would be done.",
    # )
    parser.add_argument(
        "-e",
        "--exclude",
        nargs="*",
        default="",
        help="List of glob patterns (like --exclude '*.abc' '*.vbo') to exclude.",
    )
    # parser.add_argument(
    #     "-c",
    #     "--compress",
    #     default=False,
    #     action="store_true",
    #     help="Compress blend files while copying. This option is only valid when "
    #     "packing into a directory (contrary to ZIP file or S3 upload). "
    #     "Note that files will NOT be compressed when the destination file "
    #     "already exists and has the same size as the original file.",
    # )
    parser.add_argument(
        "-r",
        "--relative-only",
        default=False,
        action="store_true",
        help="Only pack assets that are referred to with a relative path (e.g. "
        "starting with `//`.",
    )


def interpret_cli_args(args: ParsedArgs) -> CLIArgs:
    """Return paths to blendfile, project, and pack target.

    Calls sys.exit() if anything is wrong.
    """
    blendfile: Path = args.blendfile.absolute()
    if not blendfile.exists():
        log.critical("File %s does not exist", blendfile)
        sys.exit(3)
    if blendfile.is_dir():
        log.critical("%s is a directory, should be a blend file")
        sys.exit(3)

    root_path: Path = args.project.absolute() if args.project else blendfile.parent

    if not root_path.exists():
        log.critical("Project directory %s does not exist", root_path)
        sys.exit(5)

    if not root_path.is_dir():
        log.warning(
            "Project path %s is not a directory; using the parent %s",
            root_path,
            root_path.parent,
        )
        root_path = root_path.parent

    target_path: Path = args.target
    exclude_globs: set[str] = set(args.exclude)
    relative_only: bool = args.relative_only

    log.info("Blend file to pack     : %s", blendfile)
    log.info("Project path           : %s", root_path)
    log.info("Pack will be created in: %s", target_path)
    log.info("Only relative paths    : %s", relative_only)
    if exclude_globs:
        log.info("Excluding globs        : %s", ";".join(exclude_globs))

    return CLIArgs(
        blendfile=blendfile,
        target_path=target_path,
        project_root_dir=root_path,
        exclude_globs=exclude_globs,
        use_relative_only=relative_only,
    )
