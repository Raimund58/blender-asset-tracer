# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Python script for path rewriting, run in a background Blender process.

See `batter/path_rewriting_process.py` for the code that runs in the main
process, and manages this background process.
"""

import functools
import logging
import os
import queue
import sys
import threading
from multiprocessing.connection import Client, Connection
from pathlib import Path

_logger = logging.getLogger(__name__)

# Ensure Batter can be imported, even when it's not installed as package.
_my_dir = Path(__file__).resolve().parent
if str(_my_dir) not in sys.path:
    sys.path.append(str(_my_dir))

from batter import path_rewriting
from batter.path_rewriting_process import PipeMessage, PipeMsgType, RewriteRequest

type MessageQueue = queue.Queue[PipeMessage]
type RewriteQueue = queue.Queue[RewriteRequest]


def main() -> None:
    logging.basicConfig(
        format="\033[95m%(asctime)-15s %(processName)22s %(levelname)8s %(name)s %(message)s\033[0m",
        level=logging.DEBUG,
    )
    log = _logger.getChild("background_rewriter")
    log.info("Rewriter background process starting")

    connection = _connect_to_main_process()

    # Queues for incoming & outgoing messages.
    rx_queue: MessageQueue = queue.Queue()
    tx_queue: MessageQueue = queue.Queue()

    do_shutdown = threading.Event()

    rx_thread = threading.Thread(
        target=functools.partial(
            rx_thread_func,
            connection,
            rx_queue,
            do_shutdown,
            log,
        )
    )
    tx_thread = threading.Thread(
        target=functools.partial(
            tx_thread_func,
            connection,
            tx_queue,
            do_shutdown,
            log,
        )
    )
    rx_thread.start()
    tx_thread.start()

    try:
        main_loop(rx_queue, tx_queue, do_shutdown, log)
    except KeyboardInterrupt:
        log.warning("Keyboard interrupt received, shutting down the rewriter process")
        do_shutdown.set()
    except Exception:
        log.exception("Rewriter main loop had unexpected exception, shutting down")
        do_shutdown.set()

    try:
        rx_thread.join(timeout=1.0)
    except RuntimeError:
        log.exception("joining RX thread")

    try:
        tx_thread.join(timeout=1.0)
    except RuntimeError:
        log.exception("joining TX thread")

    log.debug("download process shutting down")


def main_loop(
    rx_queue: MessageQueue,
    tx_queue: MessageQueue,
    do_shutdown: threading.Event,
    log: logging.Logger,
) -> None:

    # Queue of files to rewrite.
    rewrite_queue: RewriteQueue = queue.Queue()

    while check_incoming_messages(rx_queue, rewrite_queue, do_shutdown):
        # Pop an item off the front of the queue.
        try:
            # If the queue is empty, the timeout just slows us down a bit. There
            # is no other thread that puts items into the queue, that's done in
            # check_incoming_messages().
            rewrite_request = rewrite_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        assert rewrite_request is not None
        assert isinstance(rewrite_request, RewriteRequest), (
            f"got {type(rewrite_request)}: {rewrite_request!r}"
        )

        try:
            # Convert the pipe-communication-friendly rewrite rules to a dictionary,
            # so that it's compatible again with the rest of the code.
            rewrite_rules_as_dict = dict(rewrite_request.rewrite_rules)

            # Do the actual path rewriting.
            path_rewriting.rewrite_file(
                rewrite_request.blendfile,
                rewrite_request.path_in_pack,
                rewrite_rules_as_dict,
                rewrite_request.save_to,
            )
        except Exception as ex:
            # Unexpected errors should really be logged here, as they may
            # indicate bugs (typos, dependencies not found, etc).
            log.exception(
                "unexpected error rewriting paths: %s",
                ex,
            )
            # Including the exception type ensures that the string is not empty,
            # even when str(ex) were to return an empty string. This happens,
            # for example, when raising a NotImplementedError() without explicit
            # message.
            send_report(tx_queue, rewrite_request, f"{type(ex).__name__}: {ex!s}")
        else:
            send_report(tx_queue, rewrite_request, "")


def check_incoming_messages(
    rx_queue: MessageQueue,
    rewrite_queue: RewriteQueue,
    do_shutdown: threading.Event,
) -> bool:
    """Handle received messages, and return whether we can keep running.

    This rapidly handles all incoming messages. Anything the main loop
    should do will be pushed onto the rewrite_queue.

    If any SHUTDOWN message is received, the `do_shutdown` event is set
    immediately, and `False` is returned.
    """

    while not do_shutdown.is_set():
        try:
            received_msg: PipeMessage = rx_queue.get(block=False)
        except queue.Empty:
            # Not receiving anything is fine.
            break

        match received_msg.msgtype:
            case PipeMsgType.SHUTDOWN:
                do_shutdown.set()
            case PipeMsgType.QUEUE_REWRITE:
                rewrite_queue.put(received_msg.payload)
            case PipeMsgType.REPORT:
                # Reports are sent by us, not by the other side.
                pass

    return not do_shutdown.is_set()


def send_report(
    tx_queue: MessageQueue,
    rewrite_request: RewriteRequest,
    errormsg: str,
) -> None:
    message = PipeMessage(
        msgtype=PipeMsgType.REPORT,
        payload=(rewrite_request, errormsg),
    )
    tx_queue.put(message)


def rx_thread_func(
    connection: Connection,
    rx_queue: MessageQueue,
    do_shutdown: threading.Event,
    log: logging.Logger,
) -> None:
    """Process incoming messages."""

    while not do_shutdown.is_set():
        # Always keep receiving messages while they're coming in,
        # to prevent the remote end hanging on their send() call.
        # Only once that's done should we check the do_shutdown event.
        while connection.poll():
            try:
                received_msg: PipeMessage = connection.recv()
            except (EOFError, OSError):
                # The Python documentation mentions EOFError, but in
                # practice I (Sybren) have also seen a ConnectionResetError
                # being raised when Blender shuts down uncleanly. The
                # implementation of .send() shows that it can also raise an
                # OSError, which is the superclass of ConnectionResetError
                # as well, so that's why that's caught here.
                log.warning(
                    "Blender is no longer running, shutting down the rewriter process"
                )
                do_shutdown.set()
                return

            log.info("received message: %s", received_msg)
            rx_queue.put(received_msg)


def tx_thread_func(
    connection: Connection,
    tx_queue: MessageQueue,
    do_shutdown: threading.Event,
    log: logging.Logger,
) -> None:
    """Send queued reports back to the main process."""
    while not do_shutdown.is_set():
        try:
            queued_msg = tx_queue.get(timeout=0.1)
        except queue.Empty:
            # Not having anything to transmit is fine.
            continue

        log.info("TX: sending message %s", queued_msg)
        try:
            connection.send(queued_msg)
        except OSError:
            # The Python documentation doesn't mention any exceptions for
            # the .send() function. In practice, I (Sybren) have seen a
            # BrokenPipeError being raised. The implementation of .send()
            # shows that it can also raise an OSError, which is the
            # superclass of BrokenPipeError as well.
            log.warning(
                "Blender is no longer running, shutting down the rewriter process"
            )
            do_shutdown.set()
            return


def _connect_to_main_process() -> Connection:
    listener_host: str = os.environ["LISTENER_HOST"]
    listener_port: int = int(os.environ["LISTENER_PORT"])
    listener_address = (listener_host, listener_port)

    listener_secret = os.environ["LISTENER_SECRET"]

    client = Client(listener_address, authkey=listener_secret.encode())
    return client


if __name__ == "__main__":
    main()
