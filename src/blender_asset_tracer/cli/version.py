# ***** BEGIN GPL LICENSE BLOCK *****
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# ***** END GPL LICENCE BLOCK *****
#
# (c) 2021, Blender Foundation - Sybren A. Stüvel
"""Print version of BAT and exit."""

from typing import Any

from blender_asset_tracer import __version__

# The 'argparse' module doesn't nicely expose its types.
type ArgSubParser = Any
type CLIArguments = Any


def add_parser(subparsers: ArgSubParser) -> None:
    """Add argparser for this subcommand."""

    parser = subparsers.add_parser("version", help=__doc__)
    parser.set_defaults(func=cli_version)


def cli_version(_args: CLIArguments) -> None:
    print(__version__)
