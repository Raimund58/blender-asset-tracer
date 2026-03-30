# Installation

BAT🦇 can be installed with `pip`:

```bash
$ pip3 install --user blender-asset-tracer
```

## Requirements and Dependencies

In order to run BAT v2.x you need [Blender](https://www.blender.org/download)
5.1 or newer. BAT needs to know where to find Blender, and for this it uses the
`BAT_BLENDER` environment variable.

On Linux/macOS:

```bash
$ export BAT_BLENDER=~/Downloads/blenders/blender-5.1/blender
$ bat --help
```

On Windows:

```powershell
> SET BAT_BLENDER="C:\Program Files\Blender Foundation\Blender 5.1\blender"'
> bat --help
```

Apart from Blender, BAT has very little external dependencies. It uses the
[cattrs](https://catt.rs/) library, which is bundled with Blender already.


## Development Setup

First [install UV](https://docs.astral.sh/uv/getting-started/installation/),
then run:

```bash
$ git clone https://projects.blender.org/blender/blender-asset-tracer.git
$ cd blender-asset-tracer
$ uv sync
```

For more info, see the [README.md][readme].

[readme]: https://projects.blender.org/blender/blender-asset-tracer/src/branch/main/README.md

## Building this Documentation

Run this for a live-reloading version of the documentation:

```bash
$ uv run zensical serve
```

Then visit [http://localhost:3270/](http://localhost:3270/) to see a live-reloading version of the documentation.
