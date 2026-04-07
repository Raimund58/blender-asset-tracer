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

        # Check rewriting. Since the files are rewritten by Blender, and opening
        # & saving the file will change its contents (yay pointers), we can't
        # predict the exact file paths. Here I use the 'on_rewrite_start' calls
        # to construct the mapping from input file to rewritten file path. That
        # at least will ensure that the file handling is consistent.

        rewritten_file_paths: dict[str, Path] = {}
        for blendfile, save_to in reporter.calls["on_rewrite_start"]:
            assert isinstance(blendfile, Path)
            assert isinstance(save_to, Path)
            self.assertTrue(save_to.is_relative_to(self.cache_dir), save_to)
            rewritten_file_paths[blendfile.name] = save_to

        self.assertEqual(
            {
                "scene.blend",
                "cube.blend",
                "little_cube.blend",
                "material_textures.blend",
            },
            set(rewritten_file_paths.keys()),
        )

        self.assertEqual(
            reporter.calls["on_rewrite_done"],
            reporter.calls["on_rewrite_start"],
            "All 'started' rewrites should be reported as 'done', in the same order.",
        )

        # Check that each expected file got copied.
        copies = {
            (rewritten_file_paths["scene.blend"], self.pack_dir / "scene.blend"),
            (
                rewritten_file_paths["cube.blend"],
                self.pack_dir / "char/cube.blend",
            ),
            (
                rewritten_file_paths["little_cube.blend"],
                self.pack_dir / "char/little_cube.blend",
            ),
            (
                rewritten_file_paths["material_textures.blend"],
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
