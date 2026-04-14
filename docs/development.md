# Development

This page is aimed at people who are interested in development of BAT itself. It
describes setting up a development environment, and documents some developer
tasks.

## Setting up development environment

First [install UV](https://docs.astral.sh/uv/#installation). Make sure your
shell can run the `uv` command. Run these commands:

```bash
$ git clone https://projects.blender.org/blender/blender-asset-tracer.git
$ cd blender-asset-tracer
$ uv sync                     # Create virtual environment, install dependencies.
$ uv run python run_mypy.py   # Run static type analysis.
$ uv run python run_tests.py  # Run unit tests.
```

If any of the `uv run` commands fail because they cannot find Blender, provide
the path via the `BAT_BLENDER` environment variable.


=== "Linux/macOS"
    ```bash
    $ export BAT_BLENDER=~/Downloads/blenders/blender-5.1/blender
    $ uv run python run_tests.py
    ```

=== "Windows"
    ```cmd
    > SET BAT_BLENDER="C:\Program Files\Blender Foundation\Blender 5.1\blender"
    > uv run python run_tests.py
    ```

### Historical Note

BAT v1 used Poetry for dependency management. That has a big downside, namely
that Poetry itself is made in Python. It also has its own dependencies, which
can clash with the dependencies of the project it manages. This makes it
cumbersome to work with. BAT v2 switched to [UV](https://docs.astral.sh/uv/). It
is made in Rust, so is a standalone binary, without extra dependencies to
manage, and is much faster than Poetry.


## Building this Documentation

Run this for a live-reloading version of the documentation:

```bash
$ uv run zensical serve
```

Then visit [http://localhost:3270/](http://localhost:3270/) to see a
live-reloading version of the documentation.


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
$ uv run twine check dist/blender_asset_tracer-2.0-beta2.tar.gz dist/blender_asset_tracer-2.0-beta2-*.whl
$ uv run twine upload -r bat dist/blender_asset_tracer-2.0-beta2.tar.gz dist/blender_asset_tracer-2.0-beta2-*.whl
```
