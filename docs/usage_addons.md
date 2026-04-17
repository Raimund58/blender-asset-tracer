# Usage in Blender Add-ons

This page explains the BAT packing process in a more technical way, and
documents the recommended approach for Blender add-ons that want to integrate
BAT. This is what is used in the [Flamenco](https://flamenco.blender.org/)
add-on (as of Flamenco version 3.9).

## Finding File Dependencies

To find dependencies between blend files and other files, BAT uses two Blender
API functions:

<style>
.md-typeset dl {
  --dt-indent-width: 37ex;
}
</style>

`bpy.data.user_map()`
: Returns a mapping of which data-block uses which data-block. By inspecting the
  `.library` property of these data-blocks, BAT understands the relationships
  between blend files.

`bpy.data.file_path_foreach(callback)`
: Calls the callback function for every use of an external (non-blend) file.
  These can be images, simulation caches, anything.

These two functions form the core of BAT. If your add-on needs just this
information, it can just call those functions and not bother including BAT as a
Python dependency.

Writing the Add-on
==================

Importing BAT from a Wheel File
-------------------------------

An add-on's Python dependencies should not be exposed to other add-ons. Because
of this, importing BAT into Blender is not entirely straight-forward. In short,
the add-on should do the following:

- Create a backup of `sys.path` and `sys.modules`
- Add the absolute path of the `blender-asset-tracer-*.whl` file to `sys.path`
- Import the `blender_asset_tracer` module and whatever submodules your code needs
- Restore `sys.path` and `sys.modules` from the back-up

For a concrete example, see the [Flamenco add-on][flamenco-addon].

[flamenco-addon]: https://projects.blender.org/studio/flamenco/src/branch/main/addon/flamenco

Semi Non-Blocking BAT Packing
-----------------------------

Using this approach, the BAT packing will be semi-blocking. That is, each file
copy will be blocking the UI, but in between there should be time to handle
redraws, respond to UI events, etc.

NOTE: This is example code to serve as illustration. For a complex example, see
the [Flamenco add-on][flamenco-addon].

```python
from pathlib import Path

from blender_asset_tracer import pack

# Your code needs to provide these:
project_root: Path
pack_target_dir: Path
use_relative_only: bool


class MY_OT_operator(bpy.types.Operator):
    bl_idname = "my.operator"
    bl_label = "BAT Packing Demo"
    bl_description = "Do the pack dance"
    bl_options = {"REGISTER"}  # No UNDO possible.

    def invoke(self, context: bpy.types.Context) -> set[str]:
        # Create the BAT packer.
        self.batpacker = pack.BATPacker(
            project_root,
            file_usage.Options(
                use_relative_only=use_relative_only,
            ),
            reporter=self,
            pack_target_dir=pack_target_dir,
        )

        # Set up the modal operator.
        wm = context.window_manager
        self.timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        # Perform a step of the packing process.
        if self.bat_v2_packer.step():
            return {'RUNNING_MODAL'}

        # Clean up.
        context.window_manager.event_timer_remove(self.timer)
        return {'FINISHED'}

    # Reporter Protocol, see `BATPackReporter` `blender_asset_tracer/pack.py`.
    # BAT calls these methods to let your code what it is doing.
    def on_error_on_error(self, errormsg: str, ex: Exception) -> None: ...
    def on_copy_start(self, src: Path, dest: PurePath) -> None: ...
    def on_copy_done(self, src: Path, dest: PurePath) -> None: ...
    def on_copy_error(self, src: Path, dest: PurePath, errormsg: str) -> None: ...
    def on_rewrite_error( self, blendfile: Path, save_as: Path, errormsg: str) -> None: ...
    def on_rewrite_start(self, blendfile: Path, save_as: Path) -> None: ...
    def on_rewrite_done(self, blendfile: Path, save_as: Path) -> None: ...
    def on_missing_file(self, blendfile: Path, relpath_in_pack: PurePath) -> None: ...
```
