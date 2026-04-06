# Limitations

Blender Asset Tracer v2.x runs from within Blender, and uses Blender's Python
API to understand the structure of the loaded blend file. This means that when
Blender doesn't report certain dependencies, BAT is also unaware of them.

## Blender's Known Issues

BAT v2.x requires Blender 5.1 or newer. However, there are a few known issues in
Blender 5.1.0 that cause certain dependencies to be missed:

- Blender 5.1.0 does not report legacy particle system cache files correctly.
  This is fixed in [blender!155720][pr155720], which will be part of Blender
  5.1.1.
- Blender 5.1.0 does not report Alembic file sequences correctly, see
  [blender#155774][i155774]. For now, BAT does not handle such files correctly
  either.
- Blender 5.1.0 does not report Geometry Nodes simulation cache files files, see
  [blender#155953][i155953]. As a result, BAT does not know about these files
  and will not report them as a dependency or pack them.

[pr155720]: https://projects.blender.org/blender/blender/pulls/155720
[i155774]: https://projects.blender.org/blender/blender/issues/155774
[i155953]: https://projects.blender.org/blender/blender/issues/155953

## Testing for Missing Dependencies

To test cases like the above limitations, run the following in Blender's Python
console. It should report the files in use by the current blend file:

```py
>>> {k: v for (k, v) in D.file_path_map().items() if v}
{bpy.data.objects['Plane']: {'//meshcache.mdd'}}
```

If this does _not_ report files you know are in use by your project, please
[file a bug report against Blender itself][bugreport].

[bugreport]: https://docs.blender.org/manual/en/latest/troubleshooting/report_bug.html
