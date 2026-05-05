# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import shutil
import unittest
from pathlib import Path, PurePath, PureWindowsPath

import bpy  # pyright: ignore[reportMissingImports]

from blender_asset_tracer import file_usage
from blender_asset_tracer.file_usage import PathType
from blender_asset_tracer.type_aliases import BlendFile

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
                references={None: PathType.RELATIVE},
            ),
            root / "char/little_cube.blend": file_usage.FileInfo(
                source_path=root / "char/little_cube.blend",
                needs_relocation=False,
                relpath_in_pack=PurePath("char/little_cube.blend"),
                references={None: PathType.RELATIVE},
            ),
            root.parent / "material_textures.blend": file_usage.FileInfo(
                source_path=root.parent / "material_textures.blend",
                needs_relocation=True,  # Because outside the root dir.
                relpath_in_pack=None,
                references={
                    None: PathType.RELATIVE_LIBRARY,
                    libs["cube.blend"]: PathType.RELATIVE_LIBRARY,
                    libs["little_cube.blend"]: PathType.RELATIVE_LIBRARY,
                },
            ),
            # Other assets:
            root.parent
            / "textures/Bricks/brick_dotted_04-bump.jpg": file_usage.FileInfo(
                source_path=root.parent / "textures/Bricks/brick_dotted_04-bump.jpg",
                needs_relocation=True,  # Because outside the root dir.
                relpath_in_pack=None,
                references={libs["material_textures.blend"]: PathType.RELATIVE},
            ),
            root.parent
            / "textures/Bricks/brick_dotted_04-color.jpg": file_usage.FileInfo(
                source_path=root.parent / "textures/Bricks/brick_dotted_04-color.jpg",
                needs_relocation=True,  # Because outside the root dir.
                relpath_in_pack=None,
                references={libs["material_textures.blend"]: PathType.RELATIVE},
            ),
            root.parent
            / "textures/Textures/Buildings/buildings_roof_04-color.jpg": file_usage.FileInfo(
                source_path=root.parent
                / "textures/Textures/Buildings/buildings_roof_04-color.jpg",
                needs_relocation=True,  # Because outside the root dir.
                relpath_in_pack=None,
                references={libs["material_textures.blend"]: PathType.RELATIVE},
            ),
        }

        self.maxDiff = None
        self.assertEqual(expected, deps_repo.file_infoes)

    def test_brush_libraries(self) -> None:
        infile = blendfiles / "brush_assets.blend"
        load_blendfile(infile)

        deps_repo = file_usage.FileDependencyRepository(blendfiles)
        file_usage._determine_dependencies(deps_repo, file_usage.Options())

        self.assertEqual(
            {"essentials_brushes-gp_draw.blend", "essentials_brushes-gp_vertex.blend"},
            {lib.name for lib in bpy.data.libraries},
            "Expecting this file to link to brushes from the bundled essentials.",
        )

        # The library files used to load brushes shouldn't be considered
        # dependencies of this file. Blender doesn't save those relations to the
        # blend file, and finds the brushes again in its own essentials on load.
        expected = {
            infile: file_usage.FileInfo(
                source_path=infile,
                needs_relocation=False,
                relpath_in_pack=PurePath("brush_assets.blend"),
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
                references={None: PathType.RELATIVE},
            ),
        }

        self.maxDiff = None
        self.assertEqual(expected, deps_repo.file_infoes)

    def test_mixed_linking(self) -> None:
        # Test a library that's used for both pack-linking and normal linking.
        root = blendfiles / "packed_and_normal_linking_combined"
        infile = root / "main.blend"
        load_blendfile(infile)

        deps_repo = file_usage.FileDependencyRepository(root)
        file_usage._determine_dependencies(deps_repo)

        libs = bpy.data.libraries
        expected = {
            # The currently-open blend file itself:
            infile: file_usage.FileInfo(
                source_path=infile,
                needs_relocation=False,
                relpath_in_pack=PurePath("main.blend"),
            ),
            # Library Blend files:
            root / "library.blend": file_usage.FileInfo(
                source_path=root / "library.blend",
                needs_relocation=False,
                relpath_in_pack=PurePath("library.blend"),
                references={None: PathType.RELATIVE},
            ),
            root / "gn_utils.blend": file_usage.FileInfo(
                source_path=root / "gn_utils.blend",
                needs_relocation=False,
                relpath_in_pack=PurePath("gn_utils.blend"),
                references={
                    None: PathType.RELATIVE_LIBRARY,
                    libs["library.blend"]: PathType.RELATIVE_LIBRARY,
                },
            ),
        }

        self.maxDiff = None
        self.assertEqual(expected, deps_repo.file_infoes)

    def test_links_from_lib_to_local(self) -> None:
        root = blendfiles / "blendfile_linking"
        infile = root / "main.blend"
        load_blendfile(infile)

        # Create a local mesh, and make a linked object use it.
        bpy.ops.mesh.primitive_torus_add()
        mesh_ob = bpy.context.object
        mesh_data = mesh_ob.data
        assert mesh_data.name == "Torus"

        # This will create a linked 'user' with a local 'used' datablock.
        bpy.data.objects["Suzanne"].data = mesh_data

        deps_repo = file_usage.FileDependencyRepository(root)
        file_usage._determine_dependencies(deps_repo)

        # This test blend file is properly tested in another test, so here we
        # can suffice by just checking the file paths.
        expected_paths = {
            infile,
            root / "lib_cube.blend",
            root / "lib_material.blend",
            root / "lib_suzanne.blend",
        }
        self.assertEqual(expected_paths, set(deps_repo.file_infoes.keys()))


class AbsolutePathsTest(unittest.TestCase):
    maxDiff = None
    temp_dir: Path

    def setUp(self) -> None:
        self.temp_dir = Path(bpy.app.tempdir) / "abs-path-test"
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_inside_project_nonblend(self) -> None:
        # Test what happens when file references are absolute, but still point
        # within the project root. Such paths will have to be rewritten.

        # "material_textures.blend" links a few image files.
        infile = blendfiles / "material_textures.blend"
        load_blendfile(infile)

        # Tweak the library link, so that two image data-blocks refer to the
        # same file on disk. One with absolute path, and the other with
        # relative.
        image0 = bpy.data.images["brick_dotted_04-bump"]
        image1 = bpy.data.images["brick_dotted_04-color"]
        image0.filepath = image1.filepath
        image1.filepath = bpy.path.abspath(image1.filepath)

        deps_repo = file_usage.dependencies_of_current_blendfile(blendfiles)

        expected = {
            # The currently-open blend file itself:
            infile: file_usage.FileInfo(
                source_path=infile,
                relpath_in_pack=PurePath("material_textures.blend"),
                needs_path_rewriting=True,  # Because of the absolute path.
            ),
            # Images:
            blendfiles
            / "textures/Bricks/brick_dotted_04-color.jpg": file_usage.FileInfo(
                source_path=blendfiles / "textures/Bricks/brick_dotted_04-color.jpg",
                relpath_in_pack=PurePath("textures/Bricks/brick_dotted_04-color.jpg"),
                references={None: PathType.ABSOLUTE},
            ),
            blendfiles
            / "textures/Textures/Buildings/buildings_roof_04-color.jpg": file_usage.FileInfo(
                source_path=blendfiles
                / "textures/Textures/Buildings/buildings_roof_04-color.jpg",
                relpath_in_pack=PurePath(
                    "textures/Textures/Buildings/buildings_roof_04-color.jpg"
                ),
                references={None: PathType.RELATIVE},
            ),
        }

        self.maxDiff = None
        self.assertEqual(expected, deps_repo.file_infoes)

    def test_outside_project_missing_file_builds_rewrite_rule(self) -> None:
        """Issue #92905: a missing file referenced by absolute path outside
        the project root must still get a rewrite rule, so the rewriter
        produces a `//`-relative pointer into the BAT pack instead of
        leaving the foreign-anchor absolute path intact.

        With the original code, missing-file references caused the dep
        tracer to skip building a rewrite rule. The rewriter then hit
        `KeyError` and fell back to the original absolute path, which
        crashed `Path.relative_to(walk_up=True)` whenever that path lived
        on a different filesystem anchor (e.g. a different Windows drive
        or UNC vs drive letter).
        """
        # Copy `material_textures.blend` into a fresh project root so the
        # textures it references (and the absolute path we add below) are
        # all outside the project.
        proj_root = self.temp_dir / "proj"
        proj_root.mkdir(parents=True, exist_ok=True)
        infile = proj_root / "material_textures.blend"
        shutil.copy(blendfiles / "material_textures.blend", infile)
        load_blendfile(infile)

        # Point one image at a non-existent absolute path also outside the
        # project root. This reproduces the cross-anchor scenario from the
        # bug report (asset on a different drive than the pack root) using
        # paths that are valid on the test host.
        missing_dir = self.temp_dir / "elsewhere"
        missing_path = missing_dir / "missing_image.png"
        self.assertFalse(
            missing_path.exists(),
            "This test depends on the file NOT existing on disk.",
        )
        bpy.data.images["brick_dotted_04-bump"].filepath = str(missing_path)

        deps_repo = file_usage.dependencies_of_current_blendfile(proj_root)

        # The blend file itself must be marked for path rewriting.
        blend_info = deps_repo.file_infoes[infile]
        self.assertTrue(
            blend_info.needs_path_rewriting,
            "the main blend file must be marked for rewriting because it "
            "references files by absolute path",
        )

        # The missing file must still appear in the deps repo, with a
        # relpath_in_pack inside `_outside_project/` so the BAT pack stays
        # internally consistent if the file is ever supplied later.
        missing_info = deps_repo.file_infoes[missing_path]
        self.assertIsNotNone(missing_info.relpath_in_pack)
        assert missing_info.relpath_in_pack is not None  # for type checker
        self.assertEqual(
            "_outside_project",
            missing_info.relpath_in_pack.parts[0],
            f"missing file should land under _outside_project/, got "
            f"{missing_info.relpath_in_pack}",
        )
        self.assertEqual(
            "missing_image.png",
            missing_info.relpath_in_pack.name,
            "the file name must be preserved in the relpath_in_pack",
        )

        # CRITICAL: The blend file must have a rewrite rule covering the
        # missing file's parent directory. Without this rule, the rewriter
        # falls into the cross-anchor crash path described in #92905.
        self.assertIn(
            missing_path.parent,
            blend_info.rewrite_rules,
            f"a rewrite rule must exist for missing file's parent dir; "
            f"current rules: {dict(blend_info.rewrite_rules)}",
        )
        self.assertEqual(
            missing_info.relpath_in_pack.parent,
            blend_info.rewrite_rules[missing_path.parent],
            "the rewrite rule must point at the file's location in the pack",
        )

    def test_inside_project_blendfile_direct(self) -> None:
        # Test what happens when file references are absolute, but still point
        # within the project root. Such paths will have to be rewritten.

        # "linked_cube.blend" links the cube from "basic_file.blend".
        infile = blendfiles / "linked_cube.blend"
        load_blendfile(infile)

        # Tweak the library link, so that the library blend file is referred to
        # by absolute path.
        lib = bpy.data.libraries["Lib"]
        lib.filepath = bpy.path.abspath(lib.filepath)

        deps_repo = file_usage.dependencies_of_current_blendfile(blendfiles)

        expected = {
            # The currently-open blend file itself:
            infile: file_usage.FileInfo(
                source_path=infile,
                relpath_in_pack=PurePath("linked_cube.blend"),
                needs_path_rewriting=True,  # Because the library reference needs updating.
            ),
            # Library Blend file:
            blendfiles / "basic_file.blend": file_usage.FileInfo(
                source_path=blendfiles / "basic_file.blend",
                relpath_in_pack=PurePath("basic_file.blend"),
                references={None: PathType.ABSOLUTE},
            ),
        }

        self.maxDiff = None
        self.assertEqual(expected, deps_repo.file_infoes)

    def test_inside_project_blendfile_indirect(self) -> None:
        # "main.blend" links "lib_cube.blend" and "lib_suzanne.blend".
        # "lib_cube.blend" and "lib_suzanne.blend" both link "lib_material.blend".

        # Recreate test files to use absolute paths.
        in_root = blendfiles / "blendfile_linking"
        in_path_main = in_root / "main.blend"
        in_path_lib_cube = in_root / "lib_cube.blend"
        in_path_lib_suzanne = in_root / "lib_suzanne.blend"
        in_path_lib_material = in_root / "lib_material.blend"

        path_main = self.temp_dir / "main.blend"
        path_lib_cube = self.temp_dir / "lib_cube.blend"
        path_lib_suzanne = self.temp_dir / "lib_suzanne.blend"
        path_lib_material = self.temp_dir / "lib_material.blend"

        # lib_suzanne will use an absolute path to lib_material.
        load_blendfile(in_path_lib_suzanne)
        bpy.data.libraries["lib_material.blend"].filepath = str(path_lib_material)
        save_blendfile(path_lib_suzanne)

        # lib_cube will keep a relative path to lib_material.
        shutil.copy(in_path_lib_cube, path_lib_cube)
        shutil.copy(in_path_lib_material, path_lib_material)

        # The main file will use an absolute path to lib_cube.
        load_blendfile(in_path_main)
        bpy.data.libraries["lib_cube.blend"].filepath = str(path_lib_cube)
        save_blendfile(path_main)

        root = self.temp_dir
        deps_repo = file_usage.dependencies_of_current_blendfile(root)

        # Get new references to the library datablocks, just to be independent
        # of the above code.
        lib_cube = bpy.data.libraries["lib_cube.blend"]
        lib_suzanne = bpy.data.libraries["lib_suzanne.blend"]

        # The library paths pointing to lib_material should be investigated
        # further, because that's a library that has multiple incoming links.
        expected_investigation: dict[BlendFile, set[Path]] = {
            None: {path_lib_material},
            lib_cube: {path_lib_material},
            lib_suzanne: {path_lib_material},
        }
        self.assertEqual(
            expected_investigation,
            dict(deps_repo.libraries_needing_investigation),
        )

        expected_file_infoes = {
            # The currently-open blend file itself:
            path_main: file_usage.FileInfo(
                source_path=path_main,
                relpath_in_pack=PurePath(path_main.name),
                needs_path_rewriting=True,
            ),
            path_lib_cube: file_usage.FileInfo(
                source_path=path_lib_cube,
                relpath_in_pack=PurePath("lib_cube.blend"),
                uses_absolute_library_paths=False,
                references={None: PathType.ABSOLUTE},
            ),
            path_lib_suzanne: file_usage.FileInfo(
                source_path=path_lib_suzanne,
                relpath_in_pack=PurePath("lib_suzanne.blend"),
                uses_absolute_library_paths=True,
                references={None: PathType.RELATIVE},
            ),
            path_lib_material: file_usage.FileInfo(
                source_path=path_lib_material,
                relpath_in_pack=PurePath("lib_material.blend"),
                uses_absolute_library_paths=False,
                references={
                    # These are not updated after investigating in
                    # _determine_blendfile_links(), because that just sets
                    # `uses_absolute_library_paths=True` on the file that does
                    # the linking.
                    None: PathType.RELATIVE_LIBRARY,
                    lib_cube: PathType.RELATIVE_LIBRARY,
                    lib_suzanne: PathType.RELATIVE_LIBRARY,
                },
            ),
        }

        self.assertEqual(expected_file_infoes, deps_repo.file_infoes)


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
                repo,
                abspath=path,
                reported_path=None,
                used_by_library="-none-",
                path_type=PathType.RELATIVE,
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

    def test_duplicate_paths_collapse(self) -> None:
        # Duplicate inputs cannot be made unique by suffix-trimming, but
        # `_shorten_paths` now degrades gracefully and returns the
        # collapsed mapping (keyed by original path). Duplicates simply
        # share a single shortened value. See issue #92905.
        paths = [
            Path("/local/blender/nodes"),
            Path("/local/blender/nodes"),
            Path("/studio/_flamenco/common/assets"),
            Path("/studio/_flamenco/jobs/060_0050-lighting-7qbr/pro/assets"),
        ]
        actual = file_usage._shorten_paths(paths)
        # The duplicate is collapsed to a single entry. Suffix-trimming
        # cannot produce unique short forms (because of the duplicate),
        # so the function falls back to anchor-prefixed full relative
        # form. On POSIX the anchor sanitises to ``"anchor"`` (the
        # fallback string when all anchor characters are stripped). All
        # outputs are *relative*.
        for short in actual.values():
            self.assertFalse(
                short.is_absolute(), f"shortened path {short!r} should be relative"
            )
        # Each (deduplicated) input has its own short form, and the
        # different originals don't collide.
        unique_shorts = set(actual.values())
        self.assertEqual(
            len(unique_shorts), len(set(paths)),
            f"distinct inputs should map to distinct shorts, got {actual}",
        )
        # Sanity: the original-path components survive in the short form.
        self.assertIn("nodes", actual[Path("/local/blender/nodes")].parts)
        self.assertIn(
            "assets", actual[Path("/studio/_flamenco/common/assets")].parts
        )

    def test_unc_anchor_only_input(self) -> None:
        # A UNC root like ``\\\\SERVER\\share`` has parts == (anchor,) on
        # Windows. `_shorten_paths` must produce a usable RELATIVE form
        # so that callers can safely concatenate it to a relocated root
        # (otherwise pathlib's ``/`` operator silently drops the left
        # side because the right side is absolute). See issue #92905.
        unc = PureWindowsPath("\\\\IHM-MH-SRV01\\scandaten\\")
        actual = file_usage._shorten_paths([unc])
        short = actual[unc]
        self.assertFalse(
            PurePath(short).is_absolute(),
            f"UNC anchor should shorten to a relative path, got {short!r}",
        )
        self.assertTrue(
            short.parts,
            f"UNC anchor should produce at least one path component, got {short!r}",
        )

    def test_drive_anchor_only_input(self) -> None:
        # ``D:\\`` has parts == ("D:\\",) on Windows. After stripping the
        # anchor only zero parts remain, so `_shorten_paths` must
        # synthesise a single component (``D``) rather than returning a
        # zero-part / absolute result.
        drive = PureWindowsPath("D:\\")
        actual = file_usage._shorten_paths([drive])
        short = actual[drive]
        self.assertFalse(
            PurePath(short).is_absolute(),
            f"drive anchor should shorten to a relative path, got {short!r}",
        )
        self.assertTrue(
            short.parts,
            f"drive anchor should produce at least one path component, got {short!r}",
        )

    def test_cross_anchor_same_tail_disambiguates(self) -> None:
        """Two cluster roots that share the same tail across different
        filesystem anchors must produce distinct short forms.

        Without disambiguation, ``D:\\some\\dir`` and ``E:\\some\\dir``
        would both shorten to ``some/dir``, the second overwrite the
        first in the shortened map, and `_determine_pack_paths_clustered`
        would crash with ``KeyError`` looking up the missing cluster
        root. See issue #92905.
        """
        # PureWindowsPath because POSIX `Path()` parses ``D:\\some\\dir`` as
        # a single weird component, not as drive + parts.
        roots = [
            PureWindowsPath("D:\\some\\dir"),
            PureWindowsPath("E:\\some\\dir"),
        ]
        actual = file_usage._shorten_paths(roots)
        # Every input path is present in the result mapping.
        for root in roots:
            self.assertIn(
                root, actual,
                msg=f"cluster root {root!r} missing from shortened map: {actual}",
            )
        # And the two short forms are distinct.
        self.assertNotEqual(
            actual[roots[0]], actual[roots[1]],
            msg=(
                f"distinct cross-anchor cluster roots must shorten to "
                f"distinct paths, got {actual}"
            ),
        )
        # All outputs are relative.
        for short in actual.values():
            self.assertFalse(
                PurePath(short).is_absolute(),
                f"shortened path {short!r} should be relative",
            )

    def test_cross_anchor_unc_drive_same_tail_disambiguates(self) -> None:
        """Same as above but with a UNC share alongside a drive letter."""
        roots = [
            PureWindowsPath("\\\\SERVER\\share\\common\\assets"),
            PureWindowsPath("D:\\common\\assets"),
        ]
        actual = file_usage._shorten_paths(roots)
        for root in roots:
            self.assertIn(
                root, actual,
                msg=f"cluster root {root!r} missing from shortened map: {actual}",
            )
        self.assertNotEqual(
            actual[roots[0]], actual[roots[1]],
            msg=f"got {actual}",
        )


def load_blendfile(blendfile: Path) -> None:
    # Reset Blender first. This also unloads any UI data such as brushes. When
    # loading various blend files in succession, without such a reset in
    # between, brushes are retained, which can cause unexpected libraries to
    # appear in bpy.data.libraries.
    op_result = bpy.ops.wm.read_homefile(use_empty=True)
    if "FINISHED" not in op_result:
        raise RuntimeError("Could not read empty file")

    op_result = bpy.ops.wm.open_mainfile(filepath=str(blendfile))
    if "FINISHED" not in op_result:
        raise RuntimeError(f"Could not open blend file {blendfile}: {op_result}")


def save_blendfile(blendfile: Path) -> None:
    op_result = bpy.ops.wm.save_mainfile(filepath=str(blendfile))
    if "FINISHED" not in op_result:
        raise RuntimeError(f"Could not save blend file {blendfile}: {op_result}")
