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
