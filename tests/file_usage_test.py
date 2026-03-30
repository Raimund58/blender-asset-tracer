# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from pathlib import Path, PurePath

import bpy  # pyright: ignore[reportMissingImports]

from blender_asset_tracer import file_usage

_my_dir = Path(__file__).resolve().parent
blendfiles = _my_dir.parent / "tests/blendfiles"


class FileUsageTest(unittest.TestCase):
    def tearDown(self) -> None:
        file_usage.cache_clear()

    def test_determine_dependencies(self) -> None:
        root = blendfiles / "root"
        infile = root / "scene.blend"
        load_blendfile(infile)

        deps_repo = file_usage.FileDependencyRepository(root)
        file_usage._determine_dependencies(deps_repo, file_usage.Options())

        libs = bpy.data.libraries
        expected = {
            # The currently-open blend file itself:
            infile: file_usage.FileInfo(
                source_path=infile,
                needs_relocation=False,
                relpath_in_pack=PurePath("scene.blend"),
            ),
            # Library Blend files:
            root / "char/cube.blend": file_usage.FileInfo(
                source_path=root / "char/cube.blend",
                needs_relocation=False,
                relpath_in_pack=PurePath("char/cube.blend"),
                references={None},
            ),
            root / "char/little_cube.blend": file_usage.FileInfo(
                source_path=root / "char/little_cube.blend",
                needs_relocation=False,
                relpath_in_pack=PurePath("char/little_cube.blend"),
                references={None},
            ),
            root.parent / "material_textures.blend": file_usage.FileInfo(
                source_path=root.parent / "material_textures.blend",
                needs_relocation=True,  # Because outside the root dir.
                relpath_in_pack=None,
                references={libs["cube.blend"], libs["little_cube.blend"]},
            ),
            # Other assets:
            root.parent
            / "textures/Bricks/brick_dotted_04-bump.jpg": file_usage.FileInfo(
                source_path=root.parent / "textures/Bricks/brick_dotted_04-bump.jpg",
                needs_relocation=True,  # Because outside the root dir.
                relpath_in_pack=None,
                references={libs["material_textures.blend"]},
            ),
            root.parent
            / "textures/Bricks/brick_dotted_04-color.jpg": file_usage.FileInfo(
                source_path=root.parent / "textures/Bricks/brick_dotted_04-color.jpg",
                needs_relocation=True,  # Because outside the root dir.
                relpath_in_pack=None,
                references={libs["material_textures.blend"]},
            ),
            root.parent
            / "textures/Textures/Buildings/buildings_roof_04-color.jpg": file_usage.FileInfo(
                source_path=root.parent
                / "textures/Textures/Buildings/buildings_roof_04-color.jpg",
                needs_relocation=True,  # Because outside the root dir.
                relpath_in_pack=None,
                references={libs["material_textures.blend"]},
            ),
        }

        self.maxDiff = None
        self.assertEqual(expected, deps_repo.file_infoes)

    def test_option_use_relative_only(self) -> None:
        infile = blendfiles / "absolute_path.blend"
        load_blendfile(infile)

        options = file_usage.Options(use_relative_only=True)

        deps_repo = file_usage.FileDependencyRepository(blendfiles)
        file_usage._determine_dependencies(deps_repo, options)

        expected = {
            # The currently-open blend file itself:
            infile: file_usage.FileInfo(
                source_path=infile,
                needs_relocation=False,
                relpath_in_pack=PurePath("absolute_path.blend"),
            ),
            # The only asset referred to by relative path:
            blendfiles
            / "textures/Bricks/brick_dotted_04-color.jpg": file_usage.FileInfo(
                source_path=blendfiles / "textures/Bricks/brick_dotted_04-color.jpg",
                needs_relocation=False,
                relpath_in_pack=PurePath("textures/Bricks/brick_dotted_04-color.jpg"),
                references={None},
            ),
        }

        self.maxDiff = None
        self.assertEqual(expected, deps_repo.file_infoes)


class PathsOutsideProjectsTest(unittest.TestCase):
    """Test the strategies for handling paths outside the project root."""

    def setUp(self) -> None:
        self.root1 = root1 = Path(
            "/studio/_flamenco/jobs/060_0050-lighting-7qbr/pro/assets"
        )
        self.root2 = root2 = Path("/studio/_flamenco/common/assets")
        self.paths = [
            root1 / "scripts/update_bake_path.blend",
            root1 / "nodes/distance_to_silhouette.blend",
            root1 / "brushstroke_tools/styles/brushstroke_tools-oil_brushes.blend",
            root1 / "brushstroke_tools/core/brushstroke_tools-resources.blend",
            root2 / "maps/watercolor_blended_02.png",
            root2 / "brushstroke_tools/styles/maps/oil_paint-grunge.exr",
            root2 / "brushstroke_tools/core/maps/canvas-linen_01.exr",
            root2 / "brushstroke_tools/styles/maps/watercolor-soft_bloom.exr",
            root2 / "maps/ice_shards-vertical_streaks.png",
            root1 / "fx/tendril_energy.blend",
            root1 / "nodes/background_creatures.blend",
            Path("/local/blender/nodes/geometry_nodes_essentials.blend"),
            root1 / "nodes/utilities.blend",
            root1 / "nodes/background_creatures.blen",
            root1 / "nodes/painterly_shading.blend",
            root1 / "brushstroke_tools/styles/brushstroke_tools-_brushes.blend",
            root1 / "nodes/compositing.blend",
            root2 / "nodes/tonemapper.blend",
            root2 / "maps/background_creatures/background_creatures_<UDIM>.tif",
            root2 / "maps/normal_brushstrokes.exr",
            root2 / "maps/roughness-watercolor.exr",
        ]

    def tearDown(self) -> None:
        file_usage.cache_clear()

    def test_clustered(self) -> None:
        # Create a fake setup, where all the above paths are used by the
        # currently open blend file, and none of them are in the project root.
        # This should produce three clusters:
        #
        # - /local/blender/nodes
        # - /studio/_flamenco/common/assets
        # - /studio/_flamenco/jobs/060_0050-lighting-7qbr/pro/assets
        #
        # Since there's two clusters ending in 'assets', they should be shortened to two parts:
        #
        # - blender/nodes
        # - common/assets
        # - pro/assets

        # The root path MUST be an absolute path. Starting with a slash is not
        # enough on Windows, so prefix the anchor of this Python file, to ensure
        # a valid drive letter.
        root_path = Path(blendfiles.anchor) / "nothing/is/in/the/root"
        repo = file_usage.FileDependencyRepository(root_path)
        for path in self.paths:
            file_usage._deps_repo_add_file_single(
                repo, abspath=path, reported_path=None, used_by_library=None
            )

        file_usage._determine_pack_paths_clustered(repo)

        outside = Path("_outside_project")

        # Test file in the pro/assets cluster.
        file_info = repo.file_infoes[self.root1 / "scripts/update_bake_path.blend"]
        self.assertEqual(
            outside / "pro/assets/scripts/update_bake_path.blend",
            file_info.relpath_in_pack,
        )

        # Test file in the common/assets cluster.
        file_info = repo.file_infoes[
            self.root2 / "brushstroke_tools/core/maps/canvas-linen_01.exr"
        ]
        self.assertEqual(
            outside / "common/assets/brushstroke_tools/core/maps/canvas-linen_01.exr",
            file_info.relpath_in_pack,
        )

        # Test file in the blender/nodes cluster.
        file_info = repo.file_infoes[
            Path("/local/blender/nodes/geometry_nodes_essentials.blend")
        ]
        self.assertEqual(
            outside / "blender/nodes/geometry_nodes_essentials.blend",
            file_info.relpath_in_pack,
        )


class ShortenPathsTest(unittest.TestCase):
    def test_shorten_paths(self) -> None:
        paths = [
            Path("/local/blender/nodes"),
            Path("/studio/_flamenco/common/assets"),
            Path("/studio/_flamenco/jobs/060_0050-lighting-7qbr/pro/assets"),
        ]
        actual = file_usage._shorten_paths(paths)
        expected = {
            Path("/local/blender/nodes"): Path("blender/nodes"),
            Path("/studio/_flamenco/common/assets"): Path("common/assets"),
            Path("/studio/_flamenco/jobs/060_0050-lighting-7qbr/pro/assets"): Path(
                "pro/assets"
            ),
        }

        self.maxDiff = None
        self.assertEqual(expected, actual)

    def test_duplicate_paths_error(self) -> None:
        paths = [
            Path("/local/blender/nodes"),
            Path("/local/blender/nodes"),
            Path("/studio/_flamenco/common/assets"),
            Path("/studio/_flamenco/jobs/060_0050-lighting-7qbr/pro/assets"),
        ]
        # Duplicate paths cannot be made unique, and should cause an error.
        with self.assertRaises(RuntimeError):
            file_usage._shorten_paths(paths)


def load_blendfile(blendfile: Path) -> None:
    op_result = bpy.ops.wm.open_mainfile(filepath=str(blendfile))
    if "FINISHED" not in op_result:
        raise RuntimeError(f"Could not open blend file {blendfile}: {op_result}")
