# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import inspect
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, NoReturn


def loop_via_blender(callback: Callable[[], NoReturn], script_path: Path) -> NoReturn:
    """Use Blender to run this script again.

    If already inside Blender, call the callback function.
    """

    if _is_inside_blender():
        # _reactivate_venv()
        callback()

    import shlex
    import subprocess

    blender_exe = _find_blender_exe(script_path)

    # Construct CLI arguments for Blender.
    args = [blender_exe]

    if not os.environ.get("BAT_BLENDER_VERBOSE", ""):
        args.append("-q")

    args.extend(
        [
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "47",
        ]
    )

    # If currently running inside a virtualenv, reactivate it in Blender.
    if venv := os.environ.get("VIRTUAL_ENV"):
        venv_path = Path(venv)
        match sys.platform:
            case "win32":
                site_dir = venv_path / "Lib/site-packages"
            case _:
                site_dir = next(venv_path.glob("lib/python*/site-packages"))
        assert site_dir.is_dir(), site_dir

        add_site_code = "import site; site.addsitedir({!r})".format(str(site_dir))
        args.extend(["--python-expr", add_site_code])

    # Finally, add the script to run.
    args.extend(["-P", str(script_path)])

    # Forward CLI arguments to the re-run of the script in Blender.
    if len(sys.argv) > 1:
        args.append("--")
        args.extend(sys.argv[1:])

    print(f"{script_path.stem}: Running via Blender:")
    print(f"{script_path.stem}: {shlex.join(args)}")
    print()
    proc = subprocess.run(args)
    raise SystemExit(proc.returncode)


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
