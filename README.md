# Blender Asset Tracer BAT v2

Tool to manage assets with Blender.

Blender Asset Tracer, a.k.a. BAT, is a tool for finding dependencies of blend files, and for packing those dependencies into a self-contained directory.

## Requirements

BAT v2 requires Blender 5.1 or newer.

## Known Limitations

- BAT v2 needs Blender 5.1 or newer to function.
  - Blender 5.1.0 does not report legacy particle system cache files correctly. This is fixed in [blender!155720](https://projects.blender.org/blender/blender/pulls/155720), which will be part of Blender 5.1.1.
  - Blender 5.1.0 does not report Alembic file sequences correctly, see [blender#155774](https://projects.blender.org/blender/blender/issues/155774). For now, BAT does not handle such files correctly either.
  - Blender 5.1.0 does not report Geometry Nodes simulation cache files files, see [blender#155953](https://projects.blender.org/blender/blender/issues/155953). As a result, BAT does not know about these files and will not report them as a dependency or pack them.

To test cases like the above limitations, run the following in Blender's Python console. It should report the files in use by the current blend file:

```py
>>> {k: v for (k, v) in D.file_path_map().items() if v}
{bpy.data.objects['Plane']: {'//meshcache.mdd'}}
```

## Differences between BAT v1 and v2

BAT v1 had its own logic for parsing blend files and finding paths to assets. This had certain downsides:
- Changes to Blender could introduce new paths to include, causing various reports about BAT failing to pack certain assets. BAT was basically always playing catch-up with Blender.
- It was slow, because each blend file had to be opened and inspected with Python code.
- Path rewriting would write directly to the blend file itself, simply by overwriting existing bytes. This has certain dangers of corrupting the blend file.

BAT v2 is built from the ground up to be run inside of Blender. This solves the above issues:
- Blender itself reports which paths are in use, so new developments are automatically picked up by BAT.
- Since Blender already has the information BAT needs, determining which files to use is much faster.
- Blender has an API for Python code to replace file paths. BAT v2 uses this method, ensuring that blend files stay intact.

The BAT v1 code can be found in [the v1 branch](https://projects.blender.org/blender/blender-asset-tracer/src/branch/v1/).

## Setting up development environment

First [install UV](https://docs.astral.sh/uv/#installation). Make sure your shell can run the `uv` command.
Run these commands:

```bash
$ uv sync                     # Create virtual environment, install dependencies.
$ uv run python run_mypy.py   # Run static type analysis.
$ uv run python run_tests.py  # Run unit tests.
```

If any of the `uv run` commands fail because they cannot find Blender, provide the path:

On Linux/macOS:

```bash
$ export BAT_BLENDER=~/Downloads/blenders/blender-5.1/blender
$ uv run python run_tests.py
```

On Windows:

```cmd
$ SET BAT_BLENDER="C:\Program Files\Blender Foundation\Blender 5.1\blender"'
$ uv run python run_tests.py
```

### Historical Note

BAT v1 used Poetry for dependency management. That has a big downside, namely that Poetry itself is made in Python. It also has its own dependencies, which can clash with the dependencies of the project it manages. This makes it cumbersome to work with. BAT v2 switched to [UV](https://docs.astral.sh/uv/). It is made in Rust, so is a standalone binary, without extra dependencies to manage, and is much faster than Poetry.


## Publishing a New Release

For uploading packages to PyPi, an API key is required; username+password will
not work.

First, generate an API token at https://pypi.org/manage/account/token/. Then,
use this token when publishing instead of your username and password.

As username, use `__token__`.
As password, use the token itself, including the `pypi-` prefix.

See https://pypi.org/help/#apitoken for help using API tokens to publish. This
is what I have in `~/.pypirc`:

```
[distutils]
index-servers =
    bat

# Use `twine upload -r bat` to upload with this token.
[bat]
  repository = https://upload.pypi.org/legacy/
  username = __token__
  password = pypi-abc-123-blablabla
```

### Build the release package:

```bash
$ uv build
```

### Check & upload the release package.

```
$ uv sync --group release
$ uv run twine check dist/blender_asset_tracer-2.0-beta1.tar.gz dist/blender_asset_tracer-2.0-beta1-*.whl
$ uv run twine upload -r bat dist/blender_asset_tracer-2.0-beta1.tar.gz dist/blender_asset_tracer-2.0-beta1-*.whl
```
