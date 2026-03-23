Installation
============

BAT🦇 can be installed with `pip`::

    pip3 install --user blender-asset-tracer


Requirements and Dependencies
-----------------------------

In order to run BAT v2.x you need Blender_ 5.1 or newer. BAT needs to know where
to find Blender, and for this it uses the `BAT_BLENDER` environment variable.

On Linux/macOS::

  $ export BAT_BLENDER=~/Downloads/blenders/blender-5.1/blender
  $ bat --help

On Windows::

  > SET BAT_BLENDER="C:\Program Files\Blender Foundation\Blender 5.1\blender"'
  > bat --help


Apart from Blender, BAT has very little external dependencies. It uses the
cattrs_ library, which is bundled with Blender already.

.. _`Blender`: https://www.blender.org/download
.. _`cattrs`: https://catt.rs/


Development Setup
-----------------

First `install UV`_, then run::

  git clone https://projects.blender.org/blender/blender-asset-tracer.git
  cd blender-asset-tracer
  uv sync

.. _`install UV`: https://docs.astral.sh/uv/getting-started/installation/

For more info, see `README.md <https://projects.blender.org/blender/blender-asset-tracer/src/branch/main/README.md>`_

Building this Documentation
---------------------------

Run this for a live-reloading version of the documentation::

    cd docs
    uv run sphinx-autobuild . ./_build/html
