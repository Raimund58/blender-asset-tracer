import dataclasses
import unittest
from pathlib import Path, PurePath

import bpy  # pyright: ignore[reportMissingImports]

from blender_asset_tracer import file_usage

_my_dir = Path(__file__).resolve().parent
blendfiles = _my_dir / "blendfiles"


class FileUsageTests(unittest.TestCase):
    def tearDown(self) -> None:
        file_usage.cache_clear()

    def test_packed_libraries(self) -> None:
        infile = blendfiles / "74871-packed-libraries.blend"
        load_blendfile(infile)

        deps_repo = file_usage.dependencies_of_current_blendfile(blendfiles)

        self.assertIn(infile, deps_repo.file_infoes)

        packed_lib_path = blendfiles / "A.blend"
        self.assertNotIn(packed_lib_path, deps_repo.file_infoes)

    def test_strategise_no_rewrite_required(self) -> None:
        infile = blendfiles / "doubly_linked.blend"
        load_blendfile(infile)

        deps_repo = file_usage.dependencies_of_current_blendfile(blendfiles)

        packed_files = (
            "doubly_linked.blend",
            "linked_cube.blend",
            "basic_file.blend",
            "material_textures.blend",
            "textures/Bricks/brick_dotted_04-bump.jpg",
            "textures/Bricks/brick_dotted_04-color.jpg",
        )
        for pf in packed_files:
            abs_path = blendfiles / pf
            file_info = deps_repo.file_infoes[abs_path]
            self.assertFalse(file_info.needs_path_rewriting, abs_path)
            self.assertFalse(file_info.needs_relocation, abs_path)
            self.assertEqual(Path(pf), file_info.relpath_in_pack, abs_path)

        # Check that the above for-loop tested all files.
        self.assertEqual(
            {blendfiles / pf for pf in packed_files}, set(deps_repo.file_infoes.keys())
        )

    def test_rewrite_image_sequence(self) -> None:
        infile = blendfiles / "subdir/image_sequence_dir_up.blend"
        load_blendfile(infile)

        deps_repo = file_usage.dependencies_of_current_blendfile(blendfiles)
        file_usage.determine_pack_paths_clustered(deps_repo)
        file_usage.determine_rewriting_needs(deps_repo)

        expect_repo = file_usage.FileDependencyRepository(
            root_path=blendfiles,
            packed_source_file=infile,
            file_infoes={
                blendfiles / "subdir/image_sequence_dir_up.blend": file_usage.FileInfo(
                    source_path=blendfiles / "subdir/image_sequence_dir_up.blend",
                    relpath_in_pack=PurePath("subdir/image_sequence_dir_up.blend"),
                    references={None},
                ),
                blendfiles / "imgseq/000210.png": file_usage.FileInfo(
                    source_path=blendfiles / "imgseq/000210.png",
                    relpath_in_pack=PurePath("imgseq/000210.png"),
                    references={None},
                ),
                blendfiles / "imgseq/000211.png": file_usage.FileInfo(
                    source_path=blendfiles / "imgseq/000211.png",
                    relpath_in_pack=PurePath("imgseq/000211.png"),
                    references={None},
                ),
                blendfiles / "imgseq/000212.png": file_usage.FileInfo(
                    source_path=blendfiles / "imgseq/000212.png",
                    relpath_in_pack=PurePath("imgseq/000212.png"),
                    references={None},
                ),
                blendfiles / "imgseq/000213.png": file_usage.FileInfo(
                    source_path=blendfiles / "imgseq/000213.png",
                    relpath_in_pack=PurePath("imgseq/000213.png"),
                    references={None},
                ),
                blendfiles / "imgseq/000214.png": file_usage.FileInfo(
                    source_path=blendfiles / "imgseq/000214.png",
                    relpath_in_pack=PurePath("imgseq/000214.png"),
                    references={None},
                ),
            },
        )

        # Convert to dictionary to make the test differ work for us.
        self.maxDiff = None
        self.assertEqual(dataclasses.asdict(expect_repo), dataclasses.asdict(deps_repo))

    def test_sequence_udim(self) -> None:
        # UDIM tiles are special, because the filename itself has a <UDIM>
        # marker in there and thus doesn't exist itself.
        pack_root = blendfiles / "udim"
        infile = pack_root / "v01_UDIM_BAT_debugging.blend"
        load_blendfile(infile)

        deps_repo = file_usage.dependencies_of_current_blendfile(pack_root)
        file_usage.determine_pack_paths_clustered(deps_repo)

        expect_repo = file_usage.FileDependencyRepository(
            root_path=pack_root,
            packed_source_file=infile,
            file_infoes={
                pack_root / "v01_UDIM_BAT_debugging.blend": file_usage.FileInfo(
                    source_path=pack_root / "v01_UDIM_BAT_debugging.blend",
                    relpath_in_pack=PurePath("v01_UDIM_BAT_debugging.blend"),
                    references={None},
                ),
                pack_root / "cube_UDIM.color.<UDIM>.png": file_usage.FileInfo(
                    source_path=pack_root / "cube_UDIM.color.<UDIM>.png",
                    relpath_in_pack=PurePath("cube_UDIM.color.<UDIM>.png"),
                    references={None},
                ),
            },
        )

        # Convert to dictionary to make the test differ work for us.
        self.maxDiff = None
        self.assertEqual(dataclasses.asdict(expect_repo), dataclasses.asdict(deps_repo))


class PackedAssetsTest(unittest.TestCase):
    """Test 'archive libraries' for 'packed assets'.

    See [Virtual Library Technical Design][1] and [Data-Block Embedding
    Technical Design][2] for more info.

    [1]: https://projects.blender.org/blender/blender/issues/132170
    [2]: https://projects.blender.org/blender/blender/issues/132167
    """

    def tearDown(self) -> None:
        file_usage.cache_clear()

    def test_ignore_archive_libs(self) -> None:
        """BAT should ignore archive libraries and their parent library."""
        infile = blendfiles / "packed_assets.blend"
        load_blendfile(infile)

        deps_repo = file_usage.dependencies_of_current_blendfile(blendfiles)

        # Only expect the input file, and nothing more.
        expect_repo = file_usage.FileDependencyRepository(
            root_path=blendfiles,
            packed_source_file=infile,
            file_infoes={
                blendfiles / "packed_assets.blend": file_usage.FileInfo(
                    source_path=blendfiles / "packed_assets.blend",
                    relpath_in_pack=PurePath("packed_assets.blend"),
                    references={None},
                ),
            },
        )

        # Convert to dictionary to make the test differ work for us.
        self.maxDiff = None
        self.assertEqual(dataclasses.asdict(expect_repo), dataclasses.asdict(deps_repo))


def load_blendfile(blendfile: Path) -> None:
    op_result = bpy.ops.wm.open_mainfile(filepath=str(blendfile))
    if "FINISHED" not in op_result:
        raise RuntimeError(f"Could not open blend file {blendfile}: {op_result}")
