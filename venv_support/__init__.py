# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil
import site
import sys
from pathlib import Path
from typing import Callable, NoReturn


def loop_via_blender(callback: Callable[[], NoReturn], script_path: Path) -> NoReturn:
    """Use Blender to run this script again.

    If already inside Blender, call the callback function.
    """

    if _is_inside_blender():
        _reactivate_venv()
        callback()

    import shlex
    import subprocess

    blender_exe = _find_blender_exe(script_path)
    args = (
        blender_exe,
        "-b",
        "--factory-startup",
        "--python-exit-code",
        "47",
        "--python-use-system-env",
        "-P",
        str(script_path),
    )
    print(f"{script_path.stem}: Running via Blender:")
    print(f"{script_path.stem}: \033[97m{shlex.join(args)}\033[0m")
    proc = subprocess.run(args)
    raise SystemExit(proc.returncode)


def _reactivate_venv() -> None:
    if "VIRTUAL_ENV" not in os.environ:
        return

    venv_path = Path(os.environ["VIRTUAL_ENV"])
    print(f"Reactivating virtualenv: {venv_path}")

    # Add the virtual environments libraries.
    lib_dirs = venv_path.rglob("lib/*/site-packages")
    for lib_dir in lib_dirs:
        site.addsitedir(str(lib_dir))


def _is_inside_blender() -> bool:
    """Return whether this script runs inside Blender or not."""
    # Ensure mypy can import bpy, so that it can do proper checking of imports.
    try:
        import bpy  # pyright: ignore[reportMissingImports, reportUnusedImport]  # noqa: F401
    except ImportError:
        return False
    else:
        return True


def _find_blender_exe(script_path: Path) -> str:
    """Find the Blender executable, either from $PATH or sys.argv[1]."""
    blender_exe: str | None
    if len(sys.argv) > 1:
        blender_exe = sys.argv[1]
    else:
        blender_exe = shutil.which("blender")
    if blender_exe is None:
        msg = (
            f"Cannot find blender executable, use: {script_path.name} /path/to/blender"
        )
        raise SystemExit(msg)
    return blender_exe
