# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

"""BAT packing."""

from __future__ import annotations

import collections
import functools
import logging
import shutil
import time
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, Callable, Protocol, TypeAlias

from . import file_usage, path_rewriting
from .path_rewriting_process import BackgroundRewriter, RewriteRequest

__all__ = (
    "BATPacker",
    "BATPackReporter",
    "CopyFileFunc",
)

# Function that takes arguments (source, destination) and copies a single file.
#
# The destination is always a relative path. It is up to the caller to determine
# what to do with it (prefix it with a local path, send it to the Shaman server
# as-is, etc.).
CopyFileFunc: TypeAlias = Callable[[Path, PurePath], None]

logger = logging.getLogger(__name__)


class BATPackReporter(Protocol):
    """The code below calls these functions to let the Flamenco add-on know what BAT is doing.

    TODO: include a way for Flamenco to abort the packing process.
    """

    def on_error_on_error(self, message: str, exception: Exception) -> None:
        """Called when on_copy_error() or on_rewrite_error() raise an exception."""
        ...

    def on_copy_start(self, src: Path, dest: PurePath) -> None:
        """Copying of the file starts.

        This may be called multiple times for a single file. For example, when
        uploading via HTTP to a Shaman server, the upload can fail and get
        retried.

        The on_copy_done() and on_copy_error() functions will only be called
        after the last attempt at uploading the file. This means that reported
        success/failure can be relied on to be that, and not some intermediate
        state.
        """
        ...

    def on_copy_done(self, src: Path, dest: PurePath) -> None: ...
    def on_copy_error(self, src: Path, dest: PurePath, errormsg: str) -> None: ...

    def on_rewrite_start(self, blendfile: Path, relpath_in_pack: PurePath) -> None: ...
    def on_rewrite_done(self, blendfile: Path, relpath_in_pack: PurePath) -> None: ...
    def on_rewrite_error(
        self, blendfile: Path, relpath_in_pack: PurePath, errormsg: str
    ) -> None: ...

    def on_missing_file(self, blendfile: Path, relpath_in_pack: PurePath) -> None: ...


class FileTransferProtocol(Protocol):
    def start(self, batpacker: BATPacker) -> None: ...
    def step(self) -> bool: ...
    def blendfile_location_in_pack(self) -> PurePosixPath: ...


class BATPacker:
    """BATPacker has all the logic for creating BAT packs, except file transfer.

    This class is _NOT_ necessary for general use of BAT. It adds the complexity
    necessary to create a BAT pack from a modal Blender operator.

    The class is structured as an 'execution queue machine', which can be
    started and subsequently updated until it indicates that the work is done.

    Each 'batpacker.step()' call performs a single step in the process. The
    code using this class is responsible for calling this function often enough.

    `batpacker.run_for(time_in_sec)` performs one or more steps, for as long as
    the allotted time hasn't been exceeded yet. Note that it doesn't abort any
    steps, and thus the given time WILL be exceeded.
    """

    project_root: Path
    options: file_usage.Options
    reporter: BATPackReporter

    # BAT dependency info. Contains all the files that need to be copied to the
    # render farm.
    #
    # This is only set after 'start()' is called.
    deps_repo: file_usage.FileDependencyRepository | None

    # Path rewriter process. Only created when needed.
    #
    # This is stored as a field here, instead of passed as a parameter to those
    # functions that use it, because the abort() function needs to be able to
    # find it, and shut it down.
    rewriter: BackgroundRewriter | None

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
    file_transfer: FileTransferProtocol | None

    executor: QueueingExecutor

    _is_aborted: bool
    _log: logging.Logger

    def __init__(
        self,
        project_root: Path,
        options: file_usage.Options,
        reporter: BATPackReporter,
        *,
        pack_target_dir: Path | None = None,
        file_transfer: FileTransferProtocol | None = None,
    ) -> None:
        if (pack_target_dir is None) == (file_transfer is None):
            raise ValueError(
                "pack_target_dir or file_transfer MUST be given, but not both"
            )
        self.project_root = project_root
        self.options = options
        self.reporter = reporter
        self.deps_repo = None
        self.rewriter = None
        self.pack_target_dir = pack_target_dir
        self.file_transfer = file_transfer
        self.executor = QueueingExecutor()
        self._is_aborted = False
        self._log = logger.getChild(BATPacker.__name__)

    def start(self) -> None:
        """Perform initial investigation."""

        if self.is_aborted:
            raise ValueError("this BATPacker was aborted and cannot be reused")

        self.deps_repo = file_usage.dependencies_of_current_blendfile(
            self.project_root, self.options
        )
        self.queue(self._step_rewrite_determine_files)

    def step(self) -> bool:
        """Perform a step of the packing process.

        Returns whether there are more steps to do (True) or the process is
        done (False).
        """
        if self.executor.is_done:
            return False
        self.executor.run_step()
        return not self.executor.is_done

    def run_for(self, min_duration_sec: float) -> bool:
        """Perform one or more steps of the packing process.

        Keeps performing steps for at least `min_duration_sec` seconds.

        Returns whether there are more steps to do (True) or the process is
        done (False).
        """
        if self.executor.is_done:
            return False
        self.executor.run_for(min_duration_sec)
        return not self.executor.is_done

    def abort(self) -> None:
        """Abort the packing process.

        After this 'emergency shutdown', this BATPacker should not be used.
        """
        self._log.warning("aborting")
        self._is_aborted = True
        if self.rewriter:
            self.rewriter.shutdown()
            self.rewriter = None
        self.executor.clear()

    @property
    def is_aborted(self) -> bool:
        return self._is_aborted

    def queue(self, workfunc: QueueingExecutor.WorkFunc) -> None:
        if self._is_aborted:
            # Don't queue up any more work after aborting.
            return
        self.executor.queue(workfunc)

    @property
    def is_done(self) -> bool:
        return self.executor.is_done

    def source_file_info(self) -> file_usage.FileInfo:
        """Get the FileInfo for the currently-open blend file."""
        assert self.deps_repo is not None, "call .start() first"
        return self.deps_repo.source_file_info()

    def blendfile_location_in_pack(self) -> PurePosixPath:
        """Get the path of the packed blendfile, relative to the pack root."""
        if self.file_transfer:
            return self.file_transfer.blendfile_location_in_pack()

        assert self.deps_repo is not None
        source_file_info = self.deps_repo.source_file_info()
        assert source_file_info.relpath_in_pack is not None
        return PurePosixPath(source_file_info.relpath_in_pack.as_posix())

    def _step_rewrite_determine_files(self) -> None:
        """Check which files actually need rewriting, and which ones are already cached."""
        assert self.deps_repo is not None
        blendfiles_to_rewrite = path_rewriting.determine_files_to_rewrite(
            self.deps_repo
        )

        if not blendfiles_to_rewrite:
            # Nothing to rewrite, so skip the creation of the rewriter process,
            # and go straight to the file copying.
            self.queue(self._step_copy_files_start)
            return

        self.queue(
            functools.partial(self._step_path_rewriter_create, blendfiles_to_rewrite)
        )

    def _step_path_rewriter_create(self, blendfiles_to_rewrite: set[Path]) -> None:
        """Create the path rewriter sub-process and queue up its work."""
        assert self.deps_repo is not None, "call .start() first"
        assert self.rewriter is None
        assert self.reporter is not None

        # Start the background process.
        bgrewriter = BackgroundRewriter(self.on_callback_error)
        self.rewriter = bgrewriter
        bgrewriter.start()

        # Queue up all files that need rewriting.
        for abs_path in blendfiles_to_rewrite:
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
                on_file_start=self.on_rewrite_start,
                on_file_done=self.on_rewrite_done,
                on_file_error=self.on_rewrite_error,
            )

        # The next step can check whether the rewriting is done.
        self.queue(self._step_rewrite_check)

    # Bridge between the callbacks of BackgroundRewriter and BATReporter.
    def on_rewrite_start(self, request: RewriteRequest) -> None:
        self.reporter.on_rewrite_start(request.blendfile, request.relpath_in_pack)

    def on_rewrite_done(self, request: RewriteRequest) -> None:
        self.reporter.on_rewrite_done(request.blendfile, request.relpath_in_pack)

    def on_rewrite_error(self, request: RewriteRequest, errormsg: str) -> None:
        self.reporter.on_rewrite_error(
            request.blendfile, request.relpath_in_pack, errormsg
        )

    def on_callback_error(
        self,
        request: RewriteRequest,
        ex: Exception,
        callback: BackgroundRewriter.RewriteCallback,
        callback_args: tuple[Any, ...],
    ) -> None:
        # This error means the on_rewrite_start() or on_rewrite_done()
        # callback itself caused an exception. That's a bug.
        self.abort()
        self.reporter.on_error_on_error(
            f"Callback error: {request=}  {callback=} {callback_args}",
            ex,
        )

    def _step_rewrite_check(self) -> None:
        assert self.rewriter is not None, "call _path_rewriter_create() first"

        if self.rewriter.all_rewrites_done:
            self.rewriter.shutdown()
            self.rewriter = None
            self.queue(self._step_copy_files_start)
            return

        self.rewriter.update()
        self.queue(self._step_rewrite_check)

    def _step_copy_files_start(self) -> None:
        """If there is a file transfer object given, start it up."""
        if self.file_transfer:
            self.file_transfer.start(self)
        self.queue(self._step_copy_files)

    def _step_copy_files(self) -> None:
        """Calls into the copy callback to perform the file transfer."""
        if self.file_transfer:
            has_more_work = self.file_transfer.step()
        else:
            has_more_work = self._default_file_transfer_func()

        if has_more_work:
            self.queue(self._step_copy_files)

    def all_files_to_copy(self) -> dict[Path, file_usage.FileInfo]:
        """Get the set of all files to copy.

        File Transfer Functions that need a holistic view of all the relevant
        files can use this.
        """
        assert self.deps_repo is not None, "call .start() first"
        return self.deps_repo.file_infoes

    def pop_file_to_copy(self) -> file_usage.FileInfo | None:
        """Obtain the next file to transfer.

        File Transfer Functions that work on a file-by-file basis can use this
        to get the next file they need to transfer.
        """
        assert self.deps_repo is not None, "call .start() first"
        try:
            _, file_info = self.deps_repo.file_infoes.popitem()
        except KeyError:
            return None
        return file_info

    def _default_file_transfer_func(self) -> bool:
        """Copy a single file, return whether more files may need copying."""
        assert self.pack_target_dir is not None

        file_info = self.pop_file_to_copy()
        if file_info is None:
            return False  # No more files to copy, the work is done.

        path_to_pack = file_info.path_to_pack

        target_relpath = file_info.relpath_in_pack
        assert target_relpath is not None

        if not path_to_pack.exists():
            self.reporter.on_missing_file(path_to_pack, target_relpath)
            return True  # There may be more files, so keep going.

        target_abspath = self.pack_target_dir / target_relpath

        # Copy the file.
        self.reporter.on_copy_start(path_to_pack, target_abspath)
        try:
            target_abspath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path_to_pack, target_abspath)
        except Exception as ex:
            self.reporter.on_copy_error(
                path_to_pack, target_abspath, f"{type(ex).__name__}: {ex!s}"
            )
            return True  # There may be more files, so keep going.

        self.reporter.on_copy_done(path_to_pack, target_abspath)
        return True  # There may be more files, so keep going.


class QueueingExecutor:
    """Simple work queue.

    Queue up work (a simple callable), and call `run_step()` to run the
    queued callables in order.
    """

    type WorkFunc = Callable[[], None]
    _queue: collections.deque[WorkFunc]

    # Logging calls are commented out, because they can get noisy, and
    # repr(workfunc) can get quite long too.
    _log: logging.Logger

    def __init__(self) -> None:
        self._queue = collections.deque()
        self._log = logger.getChild(QueueingExecutor.__name__)

    def queue(self, workfunc: WorkFunc) -> None:
        # self._log.debug("queueing %r", workfunc)
        self._queue.append(workfunc)

    @property
    def is_done(self) -> bool:
        return not bool(self._queue)

    def run_step(self) -> None:
        assert not self.is_done
        workfunc = self._queue.popleft()
        # self._log.debug("calling %r", workfunc)
        workfunc()

    def run_for(self, min_duration_sec: float) -> None:
        """Perform one or more steps.

        Keeps performing steps for at least `min_duration_sec` seconds.
        """
        start_time = time.monotonic() + min_duration_sec
        while self._queue and time.monotonic() - start_time < min_duration_sec:
            self.run_step()

    def clear(self) -> None:
        # self._log.debug("clearing queue")
        self._queue.clear()
