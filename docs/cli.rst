Commandline usage
=================

After installation_, ``bat --help`` will show you general usage instructions.
The command structure is::

    bat [common options] {subcommand} [subcommand-specific options]

The common options are all optional::

  -v, --verbose  Log INFO level and higher
  -d, --debug    Log everything
  -q, --quiet    Log at ERROR level and higher

For most users only ``--verbose`` is useful, the other options can be very
helpful during development or debugging.

Logging is sent to ``stderr``, whereas regular output is sent to ``stdout``.

The available subcommands are described in the next sections. Each subcommand
also takes a ``--help`` argument to get specific usage instructions.


List
----

The ``bat list`` command lists the dependencies of a blend file. When there are
no dependencies, it outputs nothing. Example::

    % bat list tests/blendfiles/doubly_linked.blend
    tests/blendfiles/doubly_linked.blend
    tests/blendfiles/basic_file.blend
    tests/blendfiles/linked_cube.blend
    tests/blendfiles/linked_cube.blend
    tests/blendfiles/material_textures.blend
    tests/blendfiles/material_textures.blend
    tests/blendfiles/textures/Bricks/brick_dotted_04-bump.jpg
    tests/blendfiles/textures/Bricks/brick_dotted_04-color.jpg


Pack
----

The ``bat pack`` command takes the dependencies as shown by ``bat list`` and
copies them to a target. This target can be a directory, a ZIP file, or
S3-compatible storage::

    bat pack [-h] [-p PROJECT] [-e [EXCLUDE ...]] [-r] blendfile target

positional arguments:
  blendfile             The Blend file to pack.
  target                Directory where to create the pack.

options:
  -h, --help            show this help message and exit
  -p, --project PROJECT
                        Root directory of your project. Paths to below this directory are kept in the BAT Pack as well, whereas
                        references to assets from outside this directory will have to be rewitten. The blend file MUST be inside
                        the project directory. If this option is ommitted, the directory containing the blend file is taken as
                        the project directoy.
  -e, --exclude [EXCLUDE ...]
                        List of glob patterns (like --exclude '*.abc' '*.vbo') to exclude.
  -r, --relative-only   Only pack assets that are referred to with a relative path (e.g. starting with `//`).

For more information see the chapter :ref:`packing`.
