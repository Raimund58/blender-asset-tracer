import dataclasses
import shutil
import tempfile
import unittest
from pathlib import Path, PurePath

import bpy  # pyright: ignore[reportMissingImports]

from blender_asset_tracer import file_usage

_my_dir = Path(__file__).resolve().parent
blendfiles = _my_dir / "blendfiles"


class FileBasedIntegrationTests(unittest.TestCase):
    """Test cases that simply load a file and inspect it reported FileInfoes."""

    def tearDown(self) -> None:
        file_usage.cache_clear()

    def test_packed_libraries(self) -> None:
        infile = blendfiles / "74871-packed-libraries.blend"
        load_blendfile(infile)

        deps_repo = file_usage.dependencies_of_current_blendfile(blendfiles)

        self.assertIn(infile, deps_repo.file_infoes)

        packed_lib_path = blendfiles / "A.blend"
        self.assertNotIn(packed_lib_path, deps_repo.file_infoes)

    def test_no_rewrite_required(self) -> None:
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

    def test_sequence_udim_no_rewriting(self) -> None:
        # UDIM tiles are special, because the filename itself has a <UDIM>
        # marker in there and thus doesn't exist itself.
        pack_root = blendfiles / "udim/same_dir"
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
                pack_root / "cube_UDIM.color.1001.png": file_usage.FileInfo(
                    source_path=pack_root / "cube_UDIM.color.1001.png",
                    reported_path=pack_root / "cube_UDIM.color.<UDIM>.png",
                    relpath_in_pack=PurePath("cube_UDIM.color.1001.png"),
                    references={None},
                ),
                pack_root / "cube_UDIM.color.1002.png": file_usage.FileInfo(
                    source_path=pack_root / "cube_UDIM.color.1002.png",
                    reported_path=pack_root / "cube_UDIM.color.<UDIM>.png",
                    relpath_in_pack=PurePath("cube_UDIM.color.1002.png"),
                    references={None},
                ),
                pack_root / "cube_UDIM.color.1003.png": file_usage.FileInfo(
                    source_path=pack_root / "cube_UDIM.color.1003.png",
                    reported_path=pack_root / "cube_UDIM.color.<UDIM>.png",
                    relpath_in_pack=PurePath("cube_UDIM.color.1003.png"),
                    references={None},
                ),
            },
        )

        # Convert to dictionary to make the test differ work for us.
        self.maxDiff = None
        self.assertEqual(dataclasses.asdict(expect_repo), dataclasses.asdict(deps_repo))

    def test_sequence_udim_with_rewriting(self) -> None:
        # UDIM tiles are special, because the filename itself has a <UDIM>
        # marker in there and thus doesn't exist itself.
        pack_root = blendfiles / "udim/needs_rewriting/root"
        infile = pack_root / "v01_UDIM_BAT_debugging.blend"
        load_blendfile(infile)

        deps_repo = file_usage.dependencies_of_current_blendfile(pack_root)
        file_usage.determine_pack_paths_clustered(deps_repo)

        udim_root_dir = pack_root.parent
        pack_udim_root_dir = PurePath("_outside_project/needs_rewriting")

        expect_repo = file_usage.FileDependencyRepository(
            root_path=pack_root,
            packed_source_file=infile,
            file_infoes={
                pack_root / "v01_UDIM_BAT_debugging.blend": file_usage.FileInfo(
                    source_path=pack_root / "v01_UDIM_BAT_debugging.blend",
                    relpath_in_pack=PurePath("v01_UDIM_BAT_debugging.blend"),
                    references={None},
                    needs_path_rewriting=True,
                    rewrite_rules={udim_root_dir: pack_udim_root_dir},
                ),
                udim_root_dir / "cube_UDIM.color.1001.png": file_usage.FileInfo(
                    source_path=udim_root_dir / "cube_UDIM.color.1001.png",
                    reported_path=udim_root_dir / "cube_UDIM.color.<UDIM>.png",
                    relpath_in_pack=pack_udim_root_dir / "cube_UDIM.color.1001.png",
                    references={None},
                    needs_relocation=True,
                ),
                udim_root_dir / "cube_UDIM.color.1002.png": file_usage.FileInfo(
                    source_path=udim_root_dir / "cube_UDIM.color.1002.png",
                    reported_path=udim_root_dir / "cube_UDIM.color.<UDIM>.png",
                    relpath_in_pack=pack_udim_root_dir / "cube_UDIM.color.1002.png",
                    references={None},
                    needs_relocation=True,
                ),
                udim_root_dir / "cube_UDIM.color.1003.png": file_usage.FileInfo(
                    source_path=udim_root_dir / "cube_UDIM.color.1003.png",
                    reported_path=udim_root_dir / "cube_UDIM.color.<UDIM>.png",
                    relpath_in_pack=pack_udim_root_dir / "cube_UDIM.color.1003.png",
                    references={None},
                    needs_relocation=True,
                ),
            },
        )

        # Convert to dictionary to make the test differ work for us.
        self.maxDiff = None
        self.assertEqual(dataclasses.asdict(expect_repo), dataclasses.asdict(deps_repo))

    def test_symlinked_files(self):
        """Test that symlinks are NOT resolved.

        A symlinked asset should be treated as if it were really at that
        location. Symlinks should NOT be resolved.
        """

        # This is the original structure when packing subdir/doubly_linked_up.blend:
        #   .
        #   ├── basic_file.blend
        #   ├── linked_cube.blend
        #   ├── material_textures.blend
        #   ├── subdir
        #   │   └── doubly_linked_up.blend
        #   └── textures
        #       └── Bricks
        #           ├── brick_dotted_04-bump.jpg
        #           └── brick_dotted_04-color.jpg

        # This test copies the files to a temporary location and renames them,
        # then recreates the above structure with symlinks. Packing the symlinks
        # should be no different than packing the originals.

        orig_paths = [
            Path("basic_file.blend"),
            Path("linked_cube.blend"),
            Path("material_textures.blend"),
            Path("subdir/doubly_linked_up.blend"),
            Path("textures/Bricks/brick_dotted_04-bump.jpg"),
            Path("textures/Bricks/brick_dotted_04-color.jpg"),
        ]

        import hashlib

        with tempfile.TemporaryDirectory(suffix="-bat-symlink") as tmpdir_str:
            tmpdir = Path(tmpdir_str)

            real_file_dir = tmpdir / "real"
            symlinked_dir = tmpdir / "symlinked"

            real_file_dir.mkdir()
            symlinked_dir.mkdir()

            for orig_path in orig_paths:
                hashed_name = hashlib.new("md5", bytes(orig_path)).hexdigest()
                # Copy the file to the temporary project, under a hashed name.
                # This will break Blendfile linking.
                real_file_path = real_file_dir / hashed_name
                shutil.copy(blendfiles / orig_path, real_file_path)

                # Create a symlink to the above file, in such a way that it
                # restores the original directory structure, and thus repairs
                # the Blendfile linking.
                symlink = symlinked_dir / orig_path
                symlink.parent.mkdir(parents=True, exist_ok=True)
                symlink.symlink_to(real_file_path)

            # Investigate the symlinked directory structure.
            load_blendfile(symlinked_dir / "subdir/doubly_linked_up.blend")
            deps_repo = file_usage.dependencies_of_current_blendfile(blendfiles)

            self.assertEqual(
                # The files should be referenced from the root dir of the
                # symlinked 'project', with the unresolved relative paths.
                {symlinked_dir / rel_path for rel_path in orig_paths},
                set(deps_repo.file_infoes.keys()),
            )

    def test_rewrite_sequence(self):
        pack_root = blendfiles / "subdir"
        infile = pack_root / "image_sequence_dir_up.blend"

        # Use a non-standard relocation root, to see if that works too.
        bat_options = file_usage.Options(relocated_root=PurePath("_relocated"))

        imgseq_root_dir = pack_root.parent / "imgseq"
        pack_imgseq_dir = bat_options.relocated_root / "imgseq"

        load_blendfile(infile)
        deps_repo = file_usage.dependencies_of_current_blendfile(
            pack_root, options=bat_options
        )

        # Construct the expected file infoes.
        expect_file_infoes = {
            infile: file_usage.FileInfo(
                source_path=infile,
                relpath_in_pack=PurePath("image_sequence_dir_up.blend"),
                references={None},
                needs_path_rewriting=True,
                rewrite_rules={imgseq_root_dir: pack_imgseq_dir},
            )
        }
        for name in (
            "000210.png",
            "000211.png",
            "000212.png",
            "000213.png",
            "000214.png",
        ):
            img_path = imgseq_root_dir / name
            expect_file_infoes[img_path] = file_usage.FileInfo(
                source_path=img_path,
                relpath_in_pack=pack_imgseq_dir / name,
                references={None},
                needs_path_rewriting=False,
                needs_relocation=True,
            )

        expect_repo = file_usage.FileDependencyRepository(
            root_path=pack_root,
            packed_source_file=infile,
            file_infoes=expect_file_infoes,
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
