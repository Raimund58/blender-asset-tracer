# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import unittest
from pathlib import Path, PurePath, PurePosixPath

from . import file_usage, hashing, path_rewriting

_my_dir = Path(__file__).resolve().parent
_testfile_root = _my_dir.parent / "tests/blendfiles"


class PathRewritingTest(unittest.TestCase):
    blendfile = _testfile_root / "root/scene.blend"

    rewrite_rules = {
        Path("/path/to/material_textures.blend"): PurePath(
            "_outside_project/material_textures.blend"
        ),
    }

    def tearDown(self) -> None:
        file_usage.cache_clear()

    def test_path_in_cache(self) -> None:
        file_info = file_usage.FileInfo(
            source_path=self.blendfile,
            relpath_in_pack=PurePath("scene.blend"),
            rewrite_rules=self.rewrite_rules,
        )

        path_in_cache = path_rewriting.path_in_cache(self.blendfile, file_info)
        expect_path = (
            path_rewriting._rewritten_files_cache_path
            / "65"
            / "658703a4f84916655fc9b1c6af7aed9c2de72e77697c4a514fb441c3dfa5474a.blend"
        )
        self.assertEqual(expect_path, path_in_cache)

    def test_ophash(self) -> None:
        file_info = file_usage.FileInfo(
            source_path=self.blendfile,
            relpath_in_pack=PurePath("scene.blend"),
            rewrite_rules=self.rewrite_rules,
        )

        # Double-check that the blend file itself hasn't changed. Otherwise this
        # test will fail in mysterious ways.
        file_hash = hashlib.sha256(self.blendfile.read_bytes()).hexdigest()
        blend_hash = "1e0eb6aef22be138082cd114cf2739ee3943f2eb1cefe8e4e97278a7f027bd2b"
        self.assertEqual(
            blend_hash,
            file_hash,
            "The file on disk has changed, test needs updating",
        )

        # Double-check that the Disk File Hash Service produces the same hash. Otherwise this
        # test will fail in mysterious ways.
        import bpy  # pyright: ignore[reportMissingImports]
        from _bpy_internal import (  # pyright: ignore[reportMissingImports]
            disk_file_hash_service as dfhs,
        )

        hash_storage_path = Path(bpy.app.cachedir) / hashing._hash_storage_cache_path
        hash_service = dfhs.get_service(hash_storage_path)
        dfhs_file_hash: str = hash_service.get_hash(
            self.blendfile, hashing._hash_algorithm
        )
        self.assertEqual(
            blend_hash,
            dfhs_file_hash,
            "The Disk File Hash Service returned an unexpected hash",
        )

        # Test the hash function.
        ophash = path_rewriting._compute_ophash(self.blendfile, file_info)
        expecthash = "658703a4f84916655fc9b1c6af7aed9c2de72e77697c4a514fb441c3dfa5474a"
        self.assertEqual(expecthash, ophash)

        # Recompute the ophash with a different filename in the pack. That
        # should keep the same hash.
        file_info.relpath_in_pack = PurePosixPath("other_scene.blend")
        ophash = path_rewriting._compute_ophash(self.blendfile, file_info)
        expecthash = "658703a4f84916655fc9b1c6af7aed9c2de72e77697c4a514fb441c3dfa5474a"
        self.assertEqual(expecthash, ophash)

        # Recompute the ophash with a different directory in the pack. That
        # should change the hash.
        file_info.relpath_in_pack = PurePosixPath("subdir/scene.blend")
        ophash = path_rewriting._compute_ophash(self.blendfile, file_info)
        expecthash = "402a3a501aa7fdaac7c8d73d82fd422664633944a8ca957de6e6f23e5fbe35c5"
        self.assertEqual(expecthash, ophash)

        # Recompute the ophash with different rewrite rules. That should change
        # the hash.
        file_info.rewrite_rules = {
            Path("/media/data/secret_stash/awesomesauce.blend"): PurePath(
                "_outside_project/secret_stash/awesomesauce.blend"
            ),
            Path("/shared/studio/ultimagic.blend"): PurePath(
                "_outside_project/studio/ultimagic.blend"
            ),
        }
        ophash = path_rewriting._compute_ophash(self.blendfile, file_info)
        expecthash = "0442caa89b8fa36dea70876fc2d1523b709cb3b61ee1480768df34ccdc941816"
        self.assertEqual(expecthash, ophash)

    def test_pathlib_assumptions(self) -> None:
        """Test the assumptions our code makes about pathlib's behaviour.

        This is mostly for documentation purposes, as pathlib itself shouldn't
        really be tested here. But given that path manipulation is so core to
        this project, I (Sybren) figured it would be good to secure these
        assumptions here.
        """

        blend_path_in_pack = PurePath("pro/shots/060_dance/060_0050-lighting.blend")
        blend_dir_in_pack = blend_path_in_pack.parent
        asset_rewritten_path = PurePath("pro/assets/nodes/gn_utils.blend")
        expect_path = PurePath("../../assets/nodes/gn_utils.blend")
        rel_path = asset_rewritten_path.relative_to(blend_dir_in_pack, walk_up=True)
        self.assertEqual(expect_path, rel_path)
