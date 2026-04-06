# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import dataclasses
import os
import shutil
import sys
import time
import unittest
from collections import defaultdict
from pathlib import Path, PurePath
from typing import Any

import bpy  # pyright: ignore[reportMissingImports]

from blender_asset_tracer import file_usage, hashing, pack, path_rewriting

from .integration_test import load_blendfile

_my_dir = Path(__file__).resolve().parent
blendfiles = _my_dir / "blendfiles"


class BATPackTest(unittest.TestCase):
    maxDiff = None

    # Backup of blender_asset_tracer.path_rewriting._rewritten_files_cache_path.
    _rewritten_files_cache_path: Path

    pack_dir: Path
    cache_dir: Path

    def setUp(self) -> None:
        """Modify path_rewriting._rewritten_files_cache_path to be unique for this test suite."""
        orig_cache_dir = path_rewriting._rewritten_files_cache_path
        self._rewritten_files_cache_path = orig_cache_dir

        self.cache_dir = orig_cache_dir.with_suffix(".unittests")
        path_rewriting._rewritten_files_cache_path = self.cache_dir

        # Start with a clean slate.
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

        # Assign a temporary directory to pack into. This doesn't have to exist yet.
        self.pack_dir = Path(bpy.app.tempdir) / "unittest-pack"

    def tearDown(self) -> None:
        """Restore path_rewriting._rewritten_files_cache_path."""

        # Clean up the old path.
        if path_rewriting._rewritten_files_cache_path.exists():
            shutil.rmtree(path_rewriting._rewritten_files_cache_path)
        # Restore the original path.
        path_rewriting._rewritten_files_cache_path = self._rewritten_files_cache_path

        # Clean up the pack directory.
        if self.pack_dir.exists():
            shutil.rmtree(self.pack_dir)

    def assertFileHashes(self, expect_hashes: dict[Path, str]) -> None:
        hasher = hashing.get_hasher()
        for path, expect_hash in expect_hashes.items():
            actual_hash = hasher(path)
            self.assertEqual(expect_hash, actual_hash, path)

    def test_batpacker_with_rewrites(self) -> None:
        # Double-check that the blend files haven't changed. Otherwise this
        # test will fail in mysterious ways.
        self.assertFileHashes({
            blendfiles / "material_textures.blend": "a857eca5bba79f293ca9898fe58ba3470dc393de0e96e1c412b429a43843aad4",
            blendfiles / "root/char/cube.blend": "cbe8787c177b08aa834a7896fc67bf38571f599bfc1efdd3139fcfab99bf4ee5",
            blendfiles / "root/char/little_cube.blend": "452bedce3b06edb2228c2269444aa41c3ba7181334e0eb572636e776bb9d9065",
            blendfiles / "root/scene.blend": "1e0eb6aef22be138082cd114cf2739ee3943f2eb1cefe8e4e97278a7f027bd2b",
        })  # fmt: skip

        # Start the actual test.
        root = blendfiles / "root"
        infile = root / "scene.blend"
        load_blendfile(infile)

        reporter = RecordingReporter()
        batpacker = pack.BATPacker(
            root,
            file_usage.Options(),
            reporter,
            pack_target_dir=self.pack_dir,
        )

        batpacker.start()
        while batpacker.step():
            # While the background process is running, don't use 100% CPU here.
            time.sleep(0.01)

        # Check that no errors occurred.
        self.assertTrue(batpacker.is_done)
        self.assertEqual([], reporter.calls["on_error_on_error"])
        self.assertEqual([], reporter.calls["on_copy_error"])
        self.assertEqual([], reporter.calls["on_rewrite_error"])
        self.assertEqual([], reporter.calls["on_missing_file"])

        # Check rewriting. Since the files are rewritten differently based on
        # the path separators, the hashes for Windows and for POSIX systems are
        # different.
        hashed = {
            "/": {
                "scene.blend": "f6/f619b3e75468c26373e00970d56249e62951a2dd39993a54d0ecd62ed4baced9.blend",
                "cube.blend": "16/1690f4f1966bc8bdbe13173c9d686ab4e503e489913e2d9792838e1836c03f89.blend",
                "little_cube.blend": "46/46db205da78f7f449af7370b8468693208061e7fbc18753ebe5a5d343921f928.blend",
                "material_textures.blend": "e5/e5a146a1b5ec74c88052d34906d30db324d04f406aba90a164e2f00e22d4fa2a.blend",
            },
            "\\": {
                "scene.blend": "08/08447c28916d98482d19031e8d3a9b3ca5110fc007ae67274da542f28546d2e9.blend",
                "cube.blend": "ba/ba72773eaa507394e8aa20b319711017e4f2f161163a719b4544e0cbcaf6f135.blend",
                "little_cube.blend": "05/05600032c6c34659f8a93d1b8564ab10e604196e6a49ebf37ec12d89b36c8005.blend",
                "material_textures.blend": "a3/a390fcfc510e0a2b4facf2bca4f6b1cbdbf27927c7570d1f006246b8fcff9777.blend",
            },
        }[os.sep]

        rewrites = {
            (blendfiles / "root/scene.blend", self.cache_dir / hashed["scene.blend"]),
            (blendfiles / "root/char/cube.blend", self.cache_dir / hashed["cube.blend"]),
            (blendfiles / "root/char/little_cube.blend", self.cache_dir / hashed["little_cube.blend"]),
            (blendfiles / "material_textures.blend", self.cache_dir / hashed["material_textures.blend"]),
        }  # fmt: skip

        self.assertEqual(rewrites, set(reporter.calls["on_rewrite_start"]))
        self.assertEqual(rewrites, set(reporter.calls["on_rewrite_done"]))

        # Check that each expected file got copied.
        copies = {
            (self.cache_dir / hashed["scene.blend"], self.pack_dir / "scene.blend"),
            (
                self.cache_dir / hashed["cube.blend"],
                self.pack_dir / "char/cube.blend",
            ),
            (
                self.cache_dir / hashed["little_cube.blend"],
                self.pack_dir / "char/little_cube.blend",
            ),
            (
                self.cache_dir / hashed["material_textures.blend"],
                self.pack_dir / "_outside_project/blendfiles/material_textures.blend",
            ),
            (
                blendfiles / "textures/Bricks/brick_dotted_04-bump.jpg",
                self.pack_dir / "_outside_project/blendfiles/textures/Bricks/brick_dotted_04-bump.jpg",
            ),
            (
                blendfiles / "textures/Bricks/brick_dotted_04-color.jpg",
                self.pack_dir / "_outside_project/blendfiles/textures/Bricks/brick_dotted_04-color.jpg",
            ),
            (
                blendfiles / "textures/Textures/Buildings/buildings_roof_04-color.jpg",
                self.pack_dir / "_outside_project/blendfiles/textures/Textures/Buildings/buildings_roof_04-color.jpg",
            ),
        }  # fmt: skip
        self.assertEqual(copies, set(reporter.calls["on_copy_start"]))
        self.assertEqual(copies, set(reporter.calls["on_copy_done"]))

        # Check that the copied files are actually there. We can't check the
        # rewritten hashes, because every rewrite will be different.
        actual_files = {p for p in self.pack_dir.rglob("*") if p.is_file()}
        expect_files = {
            self.pack_dir / "scene.blend",
            self.pack_dir / "char/little_cube.blend",
            self.pack_dir / "char/cube.blend",
            self.pack_dir / "_outside_project/blendfiles/material_textures.blend",
            self.pack_dir / "_outside_project/blendfiles/textures/Bricks/brick_dotted_04-color.jpg",
            self.pack_dir / "_outside_project/blendfiles/textures/Bricks/brick_dotted_04-bump.jpg",
            self.pack_dir / "_outside_project/blendfiles/textures/Textures/Buildings/buildings_roof_04-color.jpg",
        }  # fmt: skip
        self.assertEqual(expect_files, actual_files)

        # Final check: open each blend file and inspect the paths it uses, to
        # verify that the rewriting was succesful.
        expect_paths_per_file = {
            "scene.blend": [
                "//char/cube.blend",
                "//char/little_cube.blend",
                "//_outside_project/blendfiles/material_textures.blend",
            ],
            "char/little_cube.blend": [
                "//../_outside_project/blendfiles/material_textures.blend",
            ],
            "char/cube.blend": [
                "//../_outside_project/blendfiles/material_textures.blend",
            ],
            "_outside_project/blendfiles/material_textures.blend": [
                "//textures/Bricks/brick_dotted_04-bump.jpg",
                "//textures/Bricks/brick_dotted_04-color.jpg",
                "//textures/Textures/Buildings/buildings_roof_04-color.jpg",
            ],
        }
        actual_paths_per_file = {
            relpath: self._used_paths(self.pack_dir / relpath)
            for relpath in expect_paths_per_file
        }
        # Test all files in one go, to give an overview of all the differences
        # (instead of doing it on a file-by-file basis and stopping at the first
        # mis-match).
        self.assertEqual(expect_paths_per_file, actual_paths_per_file)

    @staticmethod
    def _used_paths(blendfile: Path) -> list[str]:
        """Return the paths directly used by this blendfile.

        Paths used by linked data are NOT included.
        """
        load_blendfile(blendfile)

        # Start with the library paths.
        paths: list[str] = [
            lib.filepath
            for lib in bpy.data.libraries
            if not file_usage.library_is_packed(lib)
            and not file_usage.library_is_archive(lib)
        ]

        # Add the non-library paths.
        def _visit_path_usage(owner_id: bpy.types.ID, path: str, _: Any) -> None:
            if owner_id.id_type == "LIBRARY":  # Libraries were handled above.
                return
            paths.append(path)

        bpy.data.file_path_foreach(
            _visit_path_usage,
            flags={"SKIP_PACKED", "SKIP_WEAK_REFERENCES", "SKIP_LINKED"},
        )

        # Normalize the paths so that unit tests can be written without taking
        # platform-specific path separators into account. Note that the test
        # files don't use UNC notation, and so this shortcut can be safely used
        # here.
        return [path.replace("\\", "/") for path in paths]


@dataclasses.dataclass
class RecordingReporter:
    """BATPackReporter that records its calls."""

    # Mapping from function name to its recorded calls.
    # Each call is a tuple of the call's arguments.
    calls: dict[str, list[tuple[Any, ...]]] = dataclasses.field(
        default_factory=lambda: defaultdict(list)
    )

    def on_error_on_error(self, message: str, exception: Exception) -> None:
        self.calls["on_error_on_error"].append((message, exception))

    def on_copy_start(self, src: Path, dest: PurePath) -> None:
        self.calls["on_copy_start"].append((src, dest))

    def on_copy_done(self, src: Path, dest: PurePath) -> None:
        self.calls["on_copy_done"].append((src, dest))

    def on_copy_error(self, src: Path, dest: PurePath, errormsg: str) -> None:
        self.calls["on_copy_error"].append((src, dest, errormsg))

    def on_rewrite_start(self, blendfile: Path, save_to: Path) -> None:
        self.calls["on_rewrite_start"].append((blendfile, save_to))

    def on_rewrite_done(self, blendfile: Path, save_to: Path) -> None:
        self.calls["on_rewrite_done"].append((blendfile, save_to))

    def on_rewrite_error(self, blendfile: Path, save_to: Path, errormsg: str) -> None:
        self.calls["on_rewrite_error"].append((blendfile, save_to, errormsg))

    def on_missing_file(self, blendfile: Path, relpath_in_pack: PurePath) -> None:
        self.calls["on_missing_file"].append((blendfile, relpath_in_pack))
