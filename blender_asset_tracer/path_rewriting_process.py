# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run Blender in a subprocess to do path-rewriting.

The `BackgroundRewriter` class runs a background Blender process, and
communicates with it to perform path rewriting on blend files.

The code in this file is meant to run in the main process. The background
process will run `path_rewriting_worker.py`.
"""

from __future__ import annotations

__all__ = (
    "BackgroundProcessNotRunningError",
    "BackgroundRewriter",
    "PipeMessage",
    "PipeMsgType",
    "RewriteRequest",
)

import copy
import dataclasses
import enum
import logging
import multiprocessing.connection
import os
import secrets
import subprocess
import time

# To work around this error:
# mypy   : Variable "multiprocessing.Event" is not valid as a type
#          note: See https://mypy.readthedocs.io/en/stable/common_issues.html#variables-vs-type-aliases
# Pylance: Variable not allowed in type expression
from multiprocessing.synchronize import Event as EventClass
from pathlib import Path, PurePath
from typing import Any, Callable

import bpy  # pyright: ignore[reportMissingImports]

from .type_aliases import RewriteRules

logger = logging.getLogger(__name__)

# Construct a script that starts the worker.
#
# This is not written as Python file for Blender to execute, so that BAT can be
# shipped as wheel file (so without the Python files directly accessible on the
# filesystem). And just in case BAT isn't directly importable, also add the
# parent directory of this file to sys.path (for when running in a development
# environment).
script_parent_dir = Path(__file__).resolve().parent.parent
worker_start_script = """
import sys
sys.path.append({!r})
import blender_asset_tracer.path_rewriting_worker
blender_asset_tracer.path_rewriting_worker.main()
""".format(str(script_parent_dir))


# On Linux, 'fork' is the default multiprocessing method. However the Python
# docs state "Note that safely forking a multithreaded process is problematic.",
# and then mention:
#
# The default start method will change away from fork in Python 3.14. Code that
# requires fork should explicitly specify that via get_context() or
# set_start_method().
#
# So I (Sybren) figure it's better to test with the 'spawn' method, which is
# also the current default on Windows and macOS.
_mp_context = multiprocessing.get_context(method="spawn")


@dataclasses.dataclass(frozen=True)
class RewriteRequest:
    blendfile: Path
    # The path of this blendfile in the pack, relative to the pack's root:
    relpath_in_pack: PurePath
    # Read-only version of the dictionary type RewriteRules.
    rewrite_rules: tuple[tuple[Path, PurePath], ...]
    save_to: Path


class PipeMsgType(enum.Enum):
    QUEUE_REWRITE = "queue"
    """Payload: RewriteRequest"""

    SHUTDOWN = "shutdown"
    """Payload: None"""

    REPORT_START = "report-start"
    """Payload: RewriteRequest"""

    REPORT_DONE = "report-done"
    """Payload: RewriteRequest"""

    REPORT_ERROR = "report-error"
    """Payload: (RewriteRequest, error message: str)"""


@dataclasses.dataclass
class PipeMessage:
    msgtype: PipeMsgType
    payload: Any


class BackgroundProcessNotRunningError(Exception):
    """The BackgroundDownloader process is not (yet) running.

    Raised when BackgroundDownloader.update() is called, but the background
    process is not yet running or has died unexpectedly.
    """


class BackgroundRewriter:
    """Manage a background Blender process for rewriting blend files."""

    _logger: logging.Logger = logger.getChild("BackgroundRewriter")

    _listener: multiprocessing.connection.Listener
    _listener_secret: str
    _connection: multiprocessing.connection.Connection

    # Keep track of which callback to call on the completion of which rewrite request.
    type FileStartCallback = Callable[[RewriteRequest], None]
    type FileDoneCallback = Callable[[RewriteRequest], None]
    type FileErrorCallback = Callable[[RewriteRequest, str], None]
    _on_start_callbacks: dict[RewriteRequest, FileStartCallback]
    _on_done_callbacks: dict[RewriteRequest, FileDoneCallback]
    _on_error_callbacks: dict[RewriteRequest, FileErrorCallback]

    type RewriteCallback = FileStartCallback | FileDoneCallback | FileErrorCallback
    type OnCallbackErrorCallback = Callable[
        [
            RewriteRequest,
            Exception,  # The exception the callback raised.
            RewriteCallback,  # The callback that failed.
            tuple[Any, ...],  # Callback's extra args after the rewrite request.
        ],
        None,
    ]
    _on_callback_error: OnCallbackErrorCallback

    _bgprocess: subprocess.Popen[bytes] | None

    _num_pending_rewrites: int

    _shutdown_event: EventClass
    _shutdown_complete_event: EventClass

    def __init__(
        self,
        on_callback_error: OnCallbackErrorCallback,
    ) -> None:
        """Create a BackgroundRewriter

        :param on_callback_error: Callback function that is called whenever the
            "on_rewrite_done" callback of a queued download raises an exception.
        """

        self._on_start_callbacks = {}
        self._on_done_callbacks = {}
        self._on_error_callbacks = {}
        self._on_callback_error = on_callback_error

        self._shutdown_event = _mp_context.Event()
        self._shutdown_complete_event = _mp_context.Event()

        self._reporters = [self]
        self._bgprocess = None
        self._num_pending_rewrites = 0
        self._logger = logger.getChild(BackgroundRewriter.__name__)

    def queue_rewrite(
        self,
        blendfile: Path,
        relpath_in_pack: PurePath,
        rewrite_rules: RewriteRules,
        save_to: Path,
        on_file_start: FileStartCallback | None = None,
        on_file_done: FileDoneCallback | None = None,
        on_file_error: FileErrorCallback | None = None,
    ) -> None:
        """Queue up a path rewrite operation."""

        if self._shutdown_event.is_set():
            raise RuntimeError(
                "BackgroundRewriter is shutting down, cannot queue new rewrites"
            )

        if self._bgprocess is None:
            raise RuntimeError(
                "BackgroundRewriter is not started yet, cannot queue rewrites"
            )

        self._num_pending_rewrites += 1

        rewrite_request = RewriteRequest(
            blendfile=blendfile,
            relpath_in_pack=relpath_in_pack,
            rewrite_rules=tuple(rewrite_rules.items()),
            save_to=save_to,
        )
        if on_file_start:
            self._on_start_callbacks[rewrite_request] = on_file_start
        if on_file_done:
            self._on_done_callbacks[rewrite_request] = on_file_done
        if on_file_error:
            self._on_error_callbacks[rewrite_request] = on_file_error

        self._connection.send(
            PipeMessage(
                msgtype=PipeMsgType.QUEUE_REWRITE,
                payload=rewrite_request,
            )
        )

    @property
    def all_rewrites_done(self) -> bool:
        return self._num_pending_rewrites == 0

    @property
    def num_pending_rewrites(self) -> int:
        return self._num_pending_rewrites

    def start(self) -> None:
        """Start the background process.

        This MUST be called before calling .update().
        """
        if self._shutdown_event.is_set():
            raise ValueError("BackgroundRewriter was shut down, cannot start again")

        # Generate a random secret. It's necessary for the
        # multiprocessing.connection stuff, and will be passed to subprocesses
        # via an environment variable.
        self._listener_secret = secrets.token_hex()
        self._listener = multiprocessing.connection.Listener(
            address=("127.0.0.1", 0), authkey=self._listener_secret.encode("ASCII")
        )

        # Pass information via environment variables.
        child_environment = copy.deepcopy(os.environ)
        child_environment["LISTENER_SECRET"] = self._listener_secret
        child_environment["LISTENER_HOST"] = self._listener.address[0]
        child_environment["LISTENER_PORT"] = str(self._listener.address[1])

        # Spawn the child Blender.
        self._logger.info("starting rewriter process")
        self._bgprocess = subprocess.Popen(
            args=[
                bpy.app.binary_path,
                "--background",
                "--factory-startup",
                "--python-expr",
                worker_start_script,
            ],
            env=child_environment,
        )

        # Wait for the process to start and create a connection.
        #
        # TODO: give this a time-out. Currently that's only possible by forcing
        # the listener to use a socket connection, then digging that socket
        # object out of the listener's internals and doing a 'select' on it.
        self._connection = self._listener.accept()

    @property
    def is_shutdown_requested(self) -> bool:
        return self._shutdown_event.is_set()

    @property
    def is_shutdown_complete(self) -> bool:
        return self._shutdown_complete_event.is_set()

    @property
    def is_subprocess_alive(self) -> bool:
        return bool(self._bgprocess and self._bgprocess.poll() is None)

    def shutdown(self) -> None:
        """Cancel any pending rewrites and shut down the background process.

        Blocks until the background process has stopped and all queued updates
        have been processed.

        NOTE: call this from the same process as used to call .update().
        """
        if self._bgprocess is None:
            self._logger.error("shutdown called while the downloader never started")
            return

        if self._shutdown_complete_event.is_set() and not self.is_subprocess_alive:
            self._logger.debug("shutdown already completed")
            return

        self._logger.debug("shutting down")
        self._shutdown_event.set()

        # Send the CANCEL message to shut down the background process.
        try:
            self._connection.send(PipeMessage(PipeMsgType.SHUTDOWN, None))
        except BrokenPipeError:
            # The other side is already shut down, which is fine.
            pass

        # Keep receiving incoming messages, to avoid the background process
        # getting stuck on a send() call.
        self._logger.debug("processing any pending updates")
        start_wait_time = time.monotonic()
        max_wait_duration = 5.0  # Seconds
        while self.is_subprocess_alive:
            if time.monotonic() - start_wait_time > max_wait_duration:
                self._logger.error("timeout waiting for background process top stop")
                # Still keep going, as there may be updates that need to be handled,
                # and it's better to continue and set self._shutdown_complete_event
                # as well.
                break
            self._handle_incoming_messages()

        return_code = self._bgprocess.wait(timeout=1)
        if return_code == 0:
            self._logger.debug("path rewrite process stopped")
        else:
            self._logger.error(
                "path rewrite process stopped with error code %d", return_code
            )
        self._listener.close()
        self._shutdown_complete_event.set()

    def update(self) -> None:
        """Call frequently to ensure the rewrite progress is reported."""
        if not self.is_subprocess_alive:
            raise BackgroundProcessNotRunningError()
        self._handle_incoming_messages()

    def _handle_incoming_messages(self) -> None:
        while True:
            # Instead of `while self._connection.poll():`, wrap in an exception
            # handler, as on Windows the `poll()` call can raise a
            # BrokenPipeError when the subprocess has ended. Maybe the `recv()`
            # call can raise that exception too, so just for safety I (Sybren)
            # put them in the same `try` block.
            try:
                if not self._connection.poll():
                    break
                msg: PipeMessage = self._connection.recv()
            except (EOFError, BrokenPipeError):
                # The remote end closed the pipe.
                break

            # These are the only message types that should be sent from the worker process.
            match msg.msgtype:
                case PipeMsgType.REPORT_START:
                    self._handle_msg_start_rewrite(msg.payload)
                case PipeMsgType.REPORT_DONE:
                    self._handle_msg_report_done(msg.payload)
                case PipeMsgType.REPORT_ERROR:
                    self._handle_msg_report_error(msg.payload)

    def _handle_msg_start_rewrite(self, request: RewriteRequest) -> None:
        if not isinstance(request, RewriteRequest):
            raise TypeError(
                f"REPORT_START message has unexpected payload type {type(request)}"
            )
        try:
            on_start_cb = self._on_start_callbacks.pop(request)
        except KeyError:
            # Not having a callback is fine.
            return
        self._call_callback(on_start_cb, request)

    def _handle_msg_report_done(self, request: RewriteRequest) -> None:
        """Handle a 'done' report from the subprocess."""
        self._mark_download_done()

        # Only check after the download is marked 'done', to prevent infinitely
        # waiting for it.
        if not isinstance(request, RewriteRequest):
            raise TypeError(
                f"REPORT_DONE message has unexpected payload type {type(request)}"
            )

        on_done_cb = self._on_done_callbacks.pop(request, None)
        if on_done_cb:
            self._logger.debug("Calling %r(%r)", on_done_cb, request)
            self._call_callback(on_done_cb, request)

    def _handle_msg_report_error(self, report: tuple[RewriteRequest, str]) -> None:
        """Handle an 'error' report from the subprocess."""
        self._mark_download_done()

        # Only check after the download is marked 'done', to prevent infinitely
        # waiting for it.
        try:
            request, errormsg = report
        except TypeError:
            raise TypeError(
                f"REPORT message has unexpected payload type {type(report)}"
            )

        on_error_cb = self._on_error_callbacks.pop(request, None)
        if on_error_cb:
            self._logger.debug("Calling %r(%r)", on_error_cb, request)
            self._call_callback(on_error_cb, request, errormsg)

    def _mark_download_done(self) -> None:
        """Reduce the number of pending downloads."""
        self._num_pending_rewrites -= 1
        assert self._num_pending_rewrites >= 0, "downloaded more files than were queued"

    def _call_callback(
        self,
        callback: RewriteCallback,
        rewrite_request: RewriteRequest,
        *extra_args: Any,
    ) -> None:
        """Call the given callback, gracefully handling errors."""

        if self._shutdown_event.is_set():
            # Do not call any callbacks any more, as the downloader is trying to shut down.
            return

        args = (rewrite_request, *extra_args)
        self._logger.debug("calling %s%r", callback.__name__, args)
        try:
            callback(*args)
        except Exception as ex:
            # Catch & log exceptions here, so that a callback causing trouble
            # doesn't break the rewriter itself.
            self._logger.debug("exception while calling {!r}".format(callback))

            try:
                self._on_callback_error(rewrite_request, ex, callback, args)
            except Exception:
                self._logger.exception(
                    "exception while handling an error in {!r}{!r}".format(
                        callback, args
                    )
                )
