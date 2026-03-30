# Packing

BAT can create BAT Packs. These packs take the form of a directory, containing
the packed blend file together with its dependencies. This includes linked blend
files, textures, fonts, Alembic files, and caches.

The blend file is inspected relative to a *project directory*. This allows BAT
to mimick the project structure as well as possible. For example, a typical
Blender Animation Studio project looks something like this:

```
/path/to/agent327
├── lib
│   ├── chars
│   │   ├── agent.blend
│   │   ├── barber.blend
│   │   ├── boris.blend
│   ├── envs
│   │   ├── barbershop_exterior.blend
│   │   ├── barbershop_interior.blend
│   │   └── elevator_shaft.blend
│   ├── maps
│   │   ├── lots-of-textures.png
│   │   └── lots-of-textures.jpg
│   ├── nodes
│   └── props
│       └── shaving_cream_brush.blend
└── scenes
     ├── 01-opening
     │   ├── 01_01_B-city_tilt
     │   ├── 01_02_A-barbershop_ext
     │   └── 01_04_B-watch
     └── 02-boris
         └── 02_01_A-car_enter
```

*(also: keep an eye on [MermaidJS issue #2645](https://github.com/mermaid-js/mermaid/issues/2645)
because we may be able to draw these trees a little nicer at some point)*

Of course this is a simplified view, but it serves the purpose of this
documentation. A BAT Pack for the Agent 327 model would include the
`agent.blend` file and its textures from the `maps` folder. To create the BAT
Pack, use the following command:

```bash
$ cd /path/to/agent327
$ bat pack --project . lib/chars/agent.blend /path/to/agent-pack
```

This will create the `/path/to/agent-pack` directory and place the following
files there:

```
/path/to/agent-pack
├── lib
│   ├── chars
│   │   ├── agent.blend
│   ├── maps
│   │   ├── lots-of-textures.png
│   │   └── lots-of-textures.jpg
│   └── props
│       └── maps
│           └── fabric_leather_bright01_col_tileable.png
└── pack-info.txt
```

The `pack-info.txt` file is created by BAT and describes that this is a BAT Pack
for `lib/chars/agent.blend`.


## Out-of-project files

Any files that are linked from outside the project will be placed in a special
directory `_outside_project` in the BAT Pack. This causes file links to
change. Let's say you want to pack a blend file
`/home/you/project/file.blend`, which uses
`/home/you/pictures/backdrop.jpg`. This will create the following BAT Pack:

```
/path/to/agent-pack
├── file.blend
├── _outside_project
│   └── pictures
│       └── backdrop.jpg
└── pack-info.txt
```

The `file.blend` will be rewritten so that it refers to the `backdrop.jpg`
inside the BAT pack, using a relative path. In this sense, the BAT Pack is a
"portable" version of the blend file.


## The Technical Process

This section describes a more technical view on the BAT packing process.

Creating BAT packs is done in a few steps. The inputs to this process are the
currently-opened blend file, the directory that acts as the 'project root', and
a set of options.

1. Using the functions above, gather information about the relevant files on
   disk, and their cross-connections (which file depends on which other files).
2. Determine the location of each file in the BAT pack.
  - For files inside the project root directory, this is simply the path
    relative to the project root.
  - For files outside outside the project root directory, these will have to be
    copied into the pack. This stage finds those files and determines the new
    location in the pack. This is called **relocation**.

3. Filter out files based on certain critera. These can be passed by code via a
   `blender_asset_tracer.file_usage.Options` object.
  - `use_relative_only`: Only include dependencies that are referred to by a
    relative path. This does _not_ cover blend files. These are always included,
    regardless of how they are referenced.
  - `ignore_globs`: set of shell globs to ignore. For example, to exclude all
    Alembic files from the BAT pack, use `*.abc` as a glob.

4. For each blend file in the pack, see if it needs **path rewriting**. This is
   necessary in two cases:
  - When a blend file references a file outside the project directory, for
    example `/home/artist/Desktop/videos/reference_video.mkv`. This is then
    stored as a 'rewrite rule' mapping `/home/artist/Desktop/videos` →
    `_outside_project/videos`.
  - When a blend file references any file by absolute path. Such a path will be
    invalid in the BAT pack, because the pack will reside in a different
    location than the original file.

  These files need **path rewriting**, because the file they reference will be
  in another location in the BAT pack.

4. Start a background process for rewriting. This opens each blend file that
   needs path rewriting, and uses `bpy.data.file_path_foreach(callback)` again
   to do so.
5. Write a `pack-info.txt` file that documents which blend file the pack was
   created from.
