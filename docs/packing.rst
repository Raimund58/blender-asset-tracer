.. _packing:

Packing
=======

BAT can create BAT Packs. These packs take the form of a directory, containing
the packed blend file together with its dependencies. This includes linked blend
files, textures, fonts, Alembic files, and caches.

The blend file is inspected relative to a *project directory*. This allows BAT
to mimick the project structure as well as possible. For example, a typical
Blender Animation Studio project looks something like this::

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

Of course this is a simplified view, but it serves the purpose of this
documentation. A BAT Pack for the Agent 327 model would include the
``agent.blend`` file and its textures from the ``maps`` folder. To create the
BAT Pack, use the following command::

    cd /path/to/agent327
    bat pack --project . lib/chars/agent.blend /path/to/agent-pack

This will create the ``/path/to/agent-pack`` directory and place the following
files there::
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

The ``pack-info.txt`` file is created by BAT and describes that this is a BAT
Pack for ``lib/chars/agent.blend``.


Out-of-project files
--------------------

Any files that are linked from outside the project will be placed in a special
directory ``_outside_project`` in the BAT Pack. This causes file links to
change. Let's say you want to pack a blend file
``/home/you/project/file.blend``, which uses
``/home/you/pictures/backdrop.jpg``. This will create the following BAT Pack::

    /path/to/agent-pack
    ├── file.blend
    ├── _outside_project
    │   └── pictures
    │       └── backdrop.jpg
    └── pack-info.txt

The ``file.blend`` will be rewritten so that it refers to the ``backdrop.jpg``
inside the BAT pack, using a relative path. In this sense, the BAT Pack is a
"portable" version of the blend file.
