#!/usr/bin/env python3

import sys
import tracemalloc
import unittest
from pathlib import Path
from typing import NoReturn

from blender_asset_tracer.venv_support import loop_via_blender

THIS_SCRIPT_PATH = Path(__file__).resolve()


class CustomTestLoader(unittest.TestLoader):
    test_pattern = "*_test.py"

    # Use a custom discovery so that the test files can end with `_test.py`.
    # This places the test files closer to the files under test, and also
    # matches Blender's test file locations in C++ and the standard Go test
    # locations.
    def discover(
        self,
        start_dir: str,
        pattern: str = "overruled-below",
        top_level_dir: str | None = None,
    ) -> unittest.suite.TestSuite:
        return super().discover(start_dir, self.test_pattern, top_level_dir)


def main() -> NoReturn:

    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1 :].copy()
    else:
        argv = []

    loader = CustomTestLoader()
    tracemalloc.start()
    test_prog = unittest.main(
        module=None,  # Triggers test file discovery.
        testLoader=loader,
        exit=False,
        argv=[THIS_SCRIPT_PATH.name, *argv],
    )
    tracemalloc.take_snapshot()

    if not test_prog.result.wasSuccessful():
        raise SystemExit(47)
    if test_prog.result.testsRun == 0:
        raise SystemExit(5)
    raise SystemExit(0)


if __name__ == "__main__":
    loop_via_blender(main, THIS_SCRIPT_PATH)
