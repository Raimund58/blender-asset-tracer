# Commandline usage

After installation_, `bat --help` will show you general usage instructions.
The command structure is:

```bash
$ bat [common options] {subcommand} [subcommand-specific options]
```

The common options are all optional:

`-v`, `--verbose`
: Log INFO level and higher

`-d`, `--debug`
: Log everything

`-q`, `--quiet`
: Log at ERROR level and higher

For most users only `--verbose` is useful, the other options can be very
helpful during development or debugging.

Logging is sent to `stderr`, whereas regular output is sent to `stdout`.

The available subcommands are described in the next sections. Each subcommand
also takes a `--help` argument to get specific usage instructions.

## List

The `bat list` command lists the dependencies of a blend file. When there are
no dependencies, it outputs nothing. Example:

```bash
$ bat list tests/blendfiles/doubly_linked.blend
tests/blendfiles/doubly_linked.blend
tests/blendfiles/basic_file.blend
tests/blendfiles/linked_cube.blend
tests/blendfiles/linked_cube.blend
tests/blendfiles/material_textures.blend
tests/blendfiles/material_textures.blend
tests/blendfiles/textures/Bricks/brick_dotted_04-bump.jpg
tests/blendfiles/textures/Bricks/brick_dotted_04-color.jpg
```

## Pack

The `bat pack` command takes the dependencies as shown by `bat list` and
copies them to a directory:

```bash
$ bat pack [--help] [-p PROJECT] [-e [EXCLUDE ...]] [-r] blendfile target
```

`blendfile`
: The Blend file to pack.

`target`
: Directory where to create the pack.

`-h`, `--help`
: show this help message and exit

`-p DIR`<br>`--project DIR`
: Root directory of your project. Paths to below this directory are kept in the
  BAT Pack as well, whereas references to assets from outside this directory
  will have to be rewitten. The blend file MUST be inside the project directory.
  If this option is ommitted, the directory containing the blend file is taken
  as the project directoy.

`-e [GLOB ...]`<br>`--exclude [GLOB ...]`
: List of glob patterns (like `--exclude '*.abc' '*.vbo'`) to exclude.

`-r`, `--relative-only`
: Only pack assets that are referred to with a relative path (e.g. starting with `//`).

For more information see [Packing](packing.md).

## Environment Variables

These environment variables are used by BAT:

`BAT_BLENDER=blender`
: Determines which Blender executable BAT uses. The default value is `blender`.
  `BAT_BLENDER` will be searched for on `$PATH`, so it doesn't have to be a full path.

:  Example: `env BAT_BLENDER=blender51 bat list the_file.blend`

`BAT_BLENDER_VERBOSE=1`
: Normally BAT runs `blender -q` to limit Blender's output and reduce noise.
  When `BAT_BLENDER_VERBOSE` is set to any value, that `-q` argument is
  ommitted, and Blender outputs its normal output.

  ```
  $ env BAT_BLENDER_VERBOSE=1 uv run bat list tests/blendfiles/doubly_linked.blend
  Blender 5.2.0 Alpha
  00:00.217  blend            | Read blend: "/home/sybren/workspace/bat/blender-asset-tracer/tests/blendfiles/doubly_linked.blend"
  Info: Read library: '/home/sybren/workspace/bat/blender-asset-tracer/tests/blendfiles/linked_cube.blend', '//linked_cube.blend', parent '<direct>'
  Info: Read library: '/home/sybren/workspace/bat/blender-asset-tracer/tests/blendfiles/material_textures.blend', '//material_textures.blend', parent '<direct>'
  Info: Read library: '/home/sybren/workspace/bat/blender-asset-tracer/tests/blendfiles/basic_file.blend', '//basic_file.blend', parent '/home/sybren/workspace/bat/blender-asset-tracer/tests/blendfiles/linked_cube.blend'
  [after this follows the normal output of 'bat list' on this file]
  ```
