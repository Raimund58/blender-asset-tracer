# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

"""BAT packing."""

from __future__ import annotations

import shutil

__all__ = (
    "BATPacker",
    "BATPackReporter",
    "BATPackState",
    "CopyFileFunc",
)

import enum
from pathlib import Path, PurePath
from typing import Callable, Protocol, TypeAlias

from . import file_usage, path_rewriting, path_rewriting_process

# Function that takes arguments (source, destination) and copies a single file.
#
# The destination is always a relative path. It is up to the caller to determine
# what to do with it (prefix it with a local path, send it to the Shaman server
# as-is, etc.).
CopyFileFunc: TypeAlias = Callable[[Path, PurePath], None]


class BATPackReporter(Protocol):
    """The code below calls these functions to let the Flamenco add-on know what BAT is doing.

    TODO: include a way for Flamenco to abort the packing process.
    """

    def on_copy_start(self, src: Path, dest: PurePath) -> None:
        pass

    def on_copy_done(self, src: Path, dest: PurePath) -> None:
        pass

    def on_copy_error(self, src: Path, dest: PurePath, errormsg: str) -> None:
        pass

    def on_rewrite_error(
        self, blendfile: Path, path_in_pack: PurePath, errormsg: str
    ) -> None:
        pass

    def on_rewrite_done(self, blendfile: Path, path_in_pack: PurePath) -> None:
        pass

    def on_missing_file(self, blendfile: Path, path_in_pack: PurePath) -> None:
        pass


class BATPackState(enum.Enum):
    STARTING = 1
    REWRITING = 2
    COPYING_FILES = 3
    DONE = 4


# FileTransferFunc performs a single file transfer.
#
# It is responsible itself for tracking which files need transferring.
# It should return True if more work is to be done, and False once everything is copied.
type FileTransferFunc = Callable[[BATPacker], bool]


class BATPacker:
    """BATPacker has all the logic for creating BAT packes except file transfer.

    This class is _NOT_ necessary for general use of BAT. It adds the complexity
    necessary to create a BAT pack from a modal Blender operator.

    The class is structured as a state machine, which can be started and
    subsequently updated until it indicates that the work is done.

    Each 'batpacker.update()' call performs a single step in the process. The
    code using this class is responsible for calling this function often enough.
    """

    state: BATPackState
    project_root: Path
    options: file_usage.Options
    reporter: BATPackReporter

    # BAT dependency info. Contains all the files that need to be copied to the
    # render farm.
    #
    # This is only set after 'start()' is called.
    deps_repo: file_usage.FileDependencyRepository | None

    # Set of files that need path rewriting before sending to the farm.
    blendfiles_to_rewrite: set[Path]

    # Path rewriter process. Only created when needed.
    rewriter: path_rewriting_process.BackgroundRewriter | None

    # Target path to write the BAT pack to.
    #
    # Providing this will make the packer create a simple filesystem based pack.
    #
    # This MUST be given if file_transfer_func is None.
    pack_target_dir: Path | None

    # Callback function for file transfers.
    #
    # Provide this to override the default filesystem based pack (for example
    # for Shaman server transfers).
    #
    # This MUST be given if pack_target_dir is None.
    file_transfer_func: FileTransferFunc | None

    # Mapping from the BAT packer state to the corresponding update function.
    # These functions can return a new state to go to, or None if no state
    # change is needed.
    _state_functions: dict[BATPackState, Callable[[], BATPackState | None]]

    def __init__(
        self,
        project_root: Path,
        options: file_usage.Options,
        reporter: BATPackReporter,
        *,
        pack_target_dir: Path | None = None,
        file_transfer_func: FileTransferFunc | None = None,
    ) -> None:
        if (pack_target_dir is None) == (file_transfer_func is None):
            raise ValueError(
                "pack_target_dir or file_transfer_func MUST be given, but not both"
            )
        self.state = BATPackState.STARTING
        self.project_root = project_root
        self.options = options
        self.reporter = reporter
        self.deps_repo = None
        self.blendfiles_to_rewrite = set()
        self.rewriter = None
        self.pack_target_dir = pack_target_dir
        self.file_transfer_func = file_transfer_func
        self._state_functions = {
            BATPackState.STARTING: self._update_starting,
            BATPackState.REWRITING: self._update_rewriting,
            BATPackState.COPYING_FILES: self._update_copying_files,
            BATPackState.DONE: self._update_done,
        }

    def start(self) -> None:
        """Perform initial investigation.

        This does not copy anything yet, just determines what needs copying/rewriting.
        """
        # Investigate the currently-open blend file, and figure out the dependencies.
        self.deps_repo = file_usage.dependencies_of_current_blendfile(
            self.project_root, self.options
        )

        # Check which files actually need rewriting, and which ones are already cached.
        self.blendfiles_to_rewrite = path_rewriting.determine_files_to_rewrite(
            self.deps_repo
        )

    def update(self) -> bool:
        """Perform a step of the packing process.

        Returns whether there are more steps to do (True) or the process is done (False).
        """
        assert self.deps_repo, "call .start() first"

        func = self._state_functions[self.state]
        new_state = func()
        if new_state is not None:
            self.state = new_state

        return self.state != BATPackState.DONE

    def abort(self) -> None:
        """Abort the packing process.

        After this 'emergency shutdown', this BATPacker should not be used.
        """
        if self.rewriter:
            self.rewriter.shutdown()
            self.rewriter = None
        self.state = BATPackState.DONE

    def source_file_info(self) -> file_usage.FileInfo:
        """Get the FileInfo for the currently-open blend file."""
        assert self.deps_repo is not None, "call .start() first"
        return self.deps_repo.source_file_info()

    def _update_starting(self) -> BATPackState:
        """Determine the first state that actually does something."""
        if self.blendfiles_to_rewrite:
            return BATPackState.REWRITING
        return BATPackState.COPYING_FILES

    def _update_rewriting(self) -> BATPackState | None:
        """Performs a path-rewriting step.

        This can be starting the path rewriter sub-process, updating the
        communication with that sub-process, or shutting it down again.
        """
        if self.rewriter is None:
            # Rewrite step 1: create the rewriter process & queue up files.
            self._path_rewriter_create()
            return None
        if not self.rewriter.all_rewrites_done:
            # Rewrite step 2: update until done.
            self.rewriter.update()
            return None
        # Rewrite step 3: shutdown and move to next state.
        self.rewriter.shutdown()
        return BATPackState.COPYING_FILES

    def _update_copying_files(self) -> BATPackState | None:
        """Calls into the copy callback to perform the file transfer."""
        if self.file_transfer_func is None:
            has_more_work = self._default_file_transfer_func()
        else:
            has_more_work = self.file_transfer_func(self)

        if has_more_work:
            return None
        return BATPackState.DONE

    def all_files_to_copy(self) -> dict[Path, file_usage.FileInfo]:
        """Get the set of all files to copy.

        File Transfer Functions that need a holistic view of all the relevant
        files can use this.
        """
        assert self.deps_repo is not None, "call .start() first"
        return self.deps_repo.file_infoes

    def pop_file_to_copy(self) -> tuple[Path, file_usage.FileInfo] | None:
        """Obtain the next file to transfer.

        File Transfer Functions that work on a file-by-file basis can use this
        to get the next file they need to transfer.
        """
        assert self.deps_repo is not None, "call .start() first"
        try:
            source_path, file_info = self.deps_repo.file_infoes.popitem()
        except KeyError:
            return None
        return source_path, file_info

    def _default_file_transfer_func(self) -> bool:
        """Copy a single file, return whether more files may need copying."""
        assert self.pack_target_dir is not None

        next_file = self.pop_file_to_copy()
        if next_file is None:
            return False  # No more files to copy, the work is done.

        source_path, file_info = next_file

        if file_info.rewritten_file_path is not None:
            source_path = file_info.rewritten_file_path

        target_relpath = file_info.relpath_in_pack
        assert target_relpath is not None

        if not source_path.exists():
            self.reporter.on_missing_file(source_path, target_relpath)
            return True  # There may be more files, so keep going.

        target_abspath = self.pack_target_dir / target_relpath

        # Copy the file.
        self.reporter.on_copy_start(source_path, target_abspath)
        try:
            target_abspath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_abspath)
        except Exception as ex:
            self.reporter.on_copy_error(
                source_path, target_abspath, f"{type(ex).__name__}: {ex!s}"
            )
            return True  # There may be more files, so keep going.

        self.reporter.on_copy_done(source_path, target_abspath)
        return True  # There may be more files, so keep going.

    def _update_done(self) -> None:
        """Doesn't do anything, as the work is done."""
        return None

    def _path_rewriter_create(self) -> None:
        """Create the path rewriter sub-process and queue up its work."""
        assert self.deps_repo is not None, "call .start() first"
        assert self.rewriter is None
        assert self.reporter is not None

        # Bridge between the callbacks of BackgroundRewriter and BATReporter.
        def on_rewrite_done(
            request: path_rewriting_process.RewriteRequest, errormsg: str
        ) -> None:
            if errormsg:
                self.reporter.on_rewrite_error(
                    request.blendfile, request.path_in_pack, errormsg
                )
            else:
                self.reporter.on_rewrite_done(request.blendfile, request.path_in_pack)

        def on_callback_error(
            request: path_rewriting_process.RewriteRequest, errormsg: str, ex: Exception
        ) -> None:
            # This error means the on_rewrite_done() callback itself caused an exception. That's a bug.
            raise RuntimeError(f"Callback error: {request=}  {errormsg=}  {ex=}")

        # Start the background process.
        bgrewriter = path_rewriting_process.BackgroundRewriter(on_callback_error)
        bgrewriter.start()
        self.rewriter = bgrewriter

        # Queue up all files that need rewriting.
        for abs_path in self.blendfiles_to_rewrite:
            file_info = self.deps_repo.file_infoes[abs_path]
            assert file_info.relpath_in_pack is not None
            assert file_info.rewritten_file_path is not None

            # Only perform path rewriting when the file actually exists. It's
            # definitely possible for a blend file to refer to missing files.
            if not abs_path.exists():
                self.reporter.on_missing_file(abs_path, file_info.relpath_in_pack)
                continue

            bgrewriter.queue_rewrite(
                abs_path,
                file_info.relpath_in_pack,
                file_info.rewrite_rules,
                file_info.rewritten_file_path,
                on_rewrite_done=on_rewrite_done,
            )

        # This is enough work for the 'create' step.
