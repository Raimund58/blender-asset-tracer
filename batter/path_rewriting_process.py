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
import batter.path_rewriting_worker
batter.path_rewriting_worker.main()
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
    path_in_pack: PurePath
    # Read-only version of the dictionary type RewriteRules.
    rewrite_rules: tuple[tuple[Path, PurePath], ...]
    save_to: Path


class PipeMsgType(enum.Enum):
    QUEUE_REWRITE = "queue"
    """Payload: RewriteRequest"""

    SHUTDOWN = "shutdown"
    """Payload: None"""

    REPORT = "report"
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
    type RewriteDoneCallback = Callable[[RewriteRequest, str], None]
    """Callback function that takes (request, error message).

    The error message is an empty string on success.
    """
    _on_rewrite_done_callbacks: dict[RewriteRequest, RewriteDoneCallback]

    type OnCallbackErrorCallback = Callable[[RewriteRequest, str, Exception], None]
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

        self._on_rewrite_done_callbacks = {}
        self._on_callback_error = on_callback_error

        self._shutdown_event = _mp_context.Event()
        self._shutdown_complete_event = _mp_context.Event()

        self._reporters = [self]
        self._bgprocess = None
        self._num_pending_rewrites = 0

    def queue_rewrite(
        self,
        blendfile: Path,
        path_in_pack: PurePath,
        rewrite_rules: RewriteRules,
        save_to: Path,
        on_rewrite_done: RewriteDoneCallback | None = None,
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
            path_in_pack=path_in_pack,
            rewrite_rules=tuple(rewrite_rules.items()),
            save_to=save_to,
        )
        if on_rewrite_done:
            self._on_rewrite_done_callbacks[rewrite_request] = on_rewrite_done

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

            assert msg.msgtype == PipeMsgType.REPORT, (
                "The only messages that should be sent to the main process are reports"
            )

            self._handle_report(msg.payload)

    def _handle_report(self, report: tuple[RewriteRequest, str]) -> None:
        """Handle a report from the subprocess."""

        # The request was done (either correctly or in error), so update the counter.
        self._mark_download_done()

        try:
            request, errormsg = report
        except TypeError:
            raise TypeError(f"report has unexpected type {type(report)}")

        self._call_on_rewrite_done_callback(request, errormsg)

    def _mark_download_done(self) -> None:
        """Reduce the number of pending downloads."""
        self._num_pending_rewrites -= 1
        assert self._num_pending_rewrites >= 0, "downloaded more files than were queued"

    def _call_on_rewrite_done_callback(
        self, rewrite_request: RewriteRequest, errormsg: str
    ) -> None:
        """Call the 'on-rewrite-done' callback for this request."""

        if self._shutdown_event.is_set():
            # Do not call any callbacks any more, as the downloader is trying to shut down.
            return

        try:
            callback = self._on_rewrite_done_callbacks.pop(rewrite_request)
        except KeyError:
            # Not having a callback is fine.
            return

        self._logger.debug("rewrite done, calling %s", callback.__name__)
        try:
            callback(rewrite_request, errormsg)
        except Exception as ex:
            # Catch & log exceptions here, so that a callback causing trouble
            # doesn't break the downloader itself.
            self._logger.debug(
                "exception while calling {!r}({!r}, {!r})".format(
                    callback, rewrite_request, errormsg
                )
            )

            try:
                self._on_callback_error(rewrite_request, errormsg, ex)
            except Exception:
                self._logger.exception(
                    "exception while handling an error in {!r}({!r}, {!r})".format(
                        callback, rewrite_request, errormsg
                    )
                )
