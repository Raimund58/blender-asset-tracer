# Installation

BAT🦇 can be installed with `pip`:

```bash
$ pip3 install blender-asset-tracer
```

## Requirements and Dependencies

In order to run BAT v2.x you need [Blender](https://www.blender.org/download)
5.1 or newer. BAT needs to know where to find Blender, and for this it uses the
`BAT_BLENDER` environment variable.

=== "Linux/macOS"
    ```bash
    $ export BAT_BLENDER=~/Downloads/blenders/blender-5.1/blender
    $ bat --help
    ```

=== "Windows"
    ```cmd
    > SET BAT_BLENDER="C:\Program Files\Blender Foundation\Blender 5.1\blender"
    > bat --help
    ```

If `BAT_BLENDER` is not set, BAT will try to run the command `blender`. If that
cannot be found, it'll show an error message.

Apart from Blender, BAT has very little external dependencies. It uses the
[cattrs](https://catt.rs/) library, which is bundled with Blender already.
