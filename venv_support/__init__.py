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

    args = [blender_exe]
    if not os.environ.get("BAT_BLENDER_VERBOSE", ""):
        args.append("-q")

    args.extend(
        [
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "47",
            "--python-use-system-env",
            "-P",
            str(script_path),
        ]
    )

    # Forward CLI arguments to the re-run of the script in Blender.
    if len(sys.argv) > 1:
        args.append("--")
        args.extend(sys.argv[1:])

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
    lib_dirs_posix = list(venv_path.rglob("lib/*/site-packages"))
    lib_dirs_windows = list(venv_path.rglob("Lib/site-packages"))
    for lib_dir in lib_dirs_posix + lib_dirs_windows:
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
    """Find the Blender executable, either from $PATH or $BAT_BLENDER."""
    bat_blender_env = os.environ.get("BAT_BLENDER") or ""
    blender_exe = shutil.which(bat_blender_env or "blender")
    if blender_exe is not None:
        return blender_exe

    if bat_blender_env:
        print(
            f"Cannot find blender executable, tried {bat_blender_env} from BAT_BLENDER:"
        )
    else:
        print("Cannot find blender executable, set BAT_BLENDER:")

    if sys.platform == "win32":
        print(
            r'  SET BAT_BLENDER="C:\Program Files\Blender Foundation\Blender 5.1\blender"'
        )
        print(f"python {script_path.name} --help")
    else:
        print(f"env BAT_BLENDER=/path/to/blender python3 {script_path.name} --help")

    raise SystemExit(47)
