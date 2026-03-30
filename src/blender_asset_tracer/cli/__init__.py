# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import datetime
import logging
import sys
import time
from typing import Any, NoReturn

# The 'argparse' module doesn't nicely expose its types.
type CLIArguments = Any


def cli_main() -> NoReturn:
    # Late-import our own modules, so that
    # `blender_asset_tracer/cli/__init__.py` can be used without BAT itself
    # being importable.
    from .. import __version__
    from . import libs, list_deps, pack, version

    parser = argparse.ArgumentParser(
        description="BAT: Blender Asset Tracer v%s" % __version__
    )

    # func is set by subparsers to indicate which function to run.
    parser.set_defaults(func=None, loglevel=logging.WARNING)
    loggroup = parser.add_mutually_exclusive_group()
    loggroup.add_argument(
        "-v",
        "--verbose",
        dest="loglevel",
        action="store_const",
        const=logging.INFO,
        help="Log INFO level and higher",
    )
    loggroup.add_argument(
        "-d",
        "--debug",
        dest="loglevel",
        action="store_const",
        const=logging.DEBUG,
        help="Log everything",
    )
    loggroup.add_argument(
        "-q",
        "--quiet",
        dest="loglevel",
        action="store_const",
        const=logging.ERROR,
        help="Log at ERROR level and higher",
    )

    subparsers = parser.add_subparsers(
        help="Choose a subcommand to actually make BAT do something. "
        "Global options go before the subcommand, "
        "whereas subcommand-specific options go after it. "
        "Use --help after the subcommand to get more info."
    )

    pack.add_parser(subparsers)
    libs.add_parser(subparsers)
    list_deps.add_parser(subparsers)
    version.add_parser(subparsers)

    # Make sure we only pass arguments after '--' to the parser. The rest are
    # arguments for Blender itself.
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1 :].copy()
    else:
        argv = []
    args = parser.parse_args(args=argv)
    config_logging(args)

    log = logging.getLogger(__name__)
    log.debug("Running BAT version %s", __version__)

    if not args.func:
        parser.error("No subcommand was given")

    start_time = time.monotonic()

    exit_code: int | None = args.func(args)

    duration = datetime.timedelta(seconds=time.monotonic() - start_time)
    log.info("Command took %s to complete", duration)

    # Just to give some space between the BAT output and Blender complaining
    # about leaked memory.
    print()
    raise SystemExit(exit_code or 0)


def config_logging(args: CLIArguments) -> None:
    """Configures the logging system based on CLI arguments."""

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)-15s %(processName)22s %(levelname)8s %(name)-40s %(message)s",
    )
    # Only set the log level on our own logger. Otherwise
    # debug logging will be completely swamped.
    logging.getLogger("blender_asset_tracer").setLevel(args.loglevel)
