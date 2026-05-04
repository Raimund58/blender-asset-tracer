# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

__version__ = "2.0.5"


from pathlib import Path

from blender_asset_tracer import cli, venv_support


def main_cli() -> None:
    """Entry point of 'bat' command configured in pyproject.toml."""
    venv_support.loop_via_blender(cli.cli_main, Path(__file__).resolve())


if __name__ == "__main__":
    main_cli()
