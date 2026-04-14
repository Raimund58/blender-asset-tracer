# History

## Change log

The changes between versions are documented in the [CHANGELOG.md][changelog] file.

[changelog]: https://projects.blender.org/blender/blender-asset-tracer/src/branch/main/CHANGELOG.md


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
