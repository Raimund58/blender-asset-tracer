#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run mypy through Blender.

This script uses Blender to run mypy, so that it can handle
`import bpy` statements.

This script expects to be able to run `blender` on the CLI.
Run this script in a virtualenv that has mypy installed:

   poetry run python run_mypy.py

If that is not possible, run the script with:

    poetry run python run_mypy.py /path/to/your/blender
"""

import os
import sys
from pathlib import Path
from typing import NoReturn

THIS_SCRIPT_PATH = Path(__file__).resolve()

sys.path.insert(0, str(THIS_SCRIPT_PATH.parent))

from blender_asset_tracer.venv_support import loop_via_blender


def main() -> NoReturn:
    import mypy.api

    # Make mypy produce color output. Without this, it somehow thinks it
    # shouldn't (even though its stdout is a terminal).
    os.environ["MYPY_FORCE_COLOR"] = "1"

    stdout, stderr, status = mypy.api.run(["--version"])
    if status:
        print("Error running mypy:")
        print(stdout)
        print(stderr, file=sys.stderr)
        raise SystemExit(status)
    print(f"Using {stdout.strip()} from {mypy.__file__}")
    print()

    # No arguments are given on the CLI, as the entire mypy config should be
    # done via pyproject.toml. That way, manually-invoked mypy will behave the
    # same as running through this script.
    result = mypy.api.run([])

    stdout, stderr, status = result

    messages = []
    if stderr:
        messages.append(stderr)
    if stdout:
        messages.append(stdout)
    if status:
        messages.append("Mypy failed with status %d" % status)

    for msg in messages:
        print(msg)

    raise SystemExit(status)


if __name__ == "__main__":
    loop_via_blender(main, THIS_SCRIPT_PATH)
