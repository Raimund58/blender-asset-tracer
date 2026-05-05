# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import unittest
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from blender_asset_tracer import file_usage, hashing, path_rewriting

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


class ComputeRewrittenPathTest(unittest.TestCase):
    """Tests for `path_rewriting._compute_rewritten_path`.

    These tests cover the three cases handled by the function:

    1. There is a rewrite rule for the asset (normal relocation case).
    2. The path is relative and there is no rewrite rule (no change).
    3. The path is absolute and there is no rewrite rule (defensive
       fallback that maps the asset into `_outside_project/` inside the
       pack, including the cross-anchor scenario from issue #92905).
    """

    # Project root inside the BAT pack, on "drive A" (mimics the bug
    # reproducer where the farm uses drive A:).
    pack_source_root = Path("/srv/farm/jobs/060_0050-lighting")
    blend_dir_in_pack = pack_source_root / "pro/shots/060_dance"

    def test_rewrite_rule_hit(self) -> None:
        """With a matching rewrite rule, the path becomes pack-relative."""
        rewrite_rules = {
            Path("/local/blender/nodes"): PurePath(
                "_outside_project/blender/nodes"
            ),
        }
        rewritten = path_rewriting._compute_rewritten_path(
            blender_path="/local/blender/nodes/gn_utils.blend",
            abs_path=Path("/local/blender/nodes/gn_utils.blend"),
            rewrite_rules=rewrite_rules,
            pack_source_root=self.pack_source_root,
            blend_dir_in_pack=self.blend_dir_in_pack,
        )
        # The rewritten path must point INTO the pack (under
        # _outside_project/), and must be //-relative to the blend file's
        # location inside the pack.
        self.assertEqual(
            "//../../../_outside_project/blender/nodes/gn_utils.blend",
            rewritten,
        )

    def test_relative_path_kept(self) -> None:
        """A relative path with no rewrite rule is kept unchanged."""
        rewritten = path_rewriting._compute_rewritten_path(
            blender_path="//textures/Bricks/brick.jpg",
            abs_path=self.pack_source_root
            / "pro/shots/060_dance/textures/Bricks/brick.jpg",
            rewrite_rules={},
            pack_source_root=self.pack_source_root,
            blend_dir_in_pack=self.blend_dir_in_pack,
        )
        # Relative paths with no rewrite rule are kept as-is, signaled by
        # returning None to Blender.
        self.assertIsNone(rewritten)

    def test_absolute_no_rule_fallback_relocates_into_pack(self) -> None:
        """Absolute path without rewrite rule lands in `_outside_project/`.

        This is the defensive fallback that protects against edge cases
        (UDIM globs matching zero files, library indirection, ...). The
        produced path MUST point INTO the pack so that the BAT pack stays
        self-contained, and so that the cross-anchor crash from issue
        #92905 cannot happen.
        """
        rewritten = path_rewriting._compute_rewritten_path(
            blender_path="/media/secret_stash/awesome.png",
            abs_path=Path("/media/secret_stash/awesome.png"),
            rewrite_rules={},
            pack_source_root=self.pack_source_root,
            blend_dir_in_pack=self.blend_dir_in_pack,
        )
        # The rewritten path:
        # - Starts with `//` (blendfile-relative).
        # - Walks up to the pack root and then down into
        #   `_outside_project/<safe path>`.
        # - Has POSIX-style separators.
        self.assertEqual(
            "//../../../_outside_project/media/secret_stash/awesome.png",
            rewritten,
        )

    def test_absolute_no_rule_fallback_cross_drive_windows(self) -> None:
        """Issue #92905: cross-drive Windows path falls back without crashing.

        With the original code, an absolute path on a different Windows
        drive than the pack root would propagate through the rewriter
        unchanged, and `Path.relative_to(blend_dir_in_pack, walk_up=True)`
        would raise `ValueError: ... have different anchors`.

        After the fix, the path is mapped into `_outside_project/` inside
        the pack and the `relative_to(walk_up=True)` call is anchor-safe.
        """
        # Mimic the exact reproducer from the bug: pack on `A:`, asset on
        # `D:`. We use `PureWindowsPath` so this test runs on POSIX hosts
        # too; the bug only manifests on Windows but the path-handling
        # logic itself is platform-independent.
        pack_source_root = PureWindowsPath(
            r"A:\1 Amazon_Active_Projects\260422_Upstream_edits_2026\Blends"
        )
        blend_dir_in_pack = pack_source_root / "shots/scene"
        cross_drive_abs = PureWindowsPath(
            r"D:\2.ToDraw\Amazon Projects\image (1).png"
        )

        rewritten = path_rewriting._compute_rewritten_path(
            blender_path=str(cross_drive_abs),
            abs_path=cross_drive_abs,
            rewrite_rules={},
            pack_source_root=pack_source_root,
            blend_dir_in_pack=blend_dir_in_pack,
        )

        # The result is a `//`-relative path pointing into the pack's
        # `_outside_project/` directory, with POSIX separators (Blender
        # uses POSIX in its own path strings).
        self.assertEqual(
            "//../../_outside_project/2.ToDraw/Amazon Projects/image (1).png",
            rewritten,
        )
        # Sanity: the produced path must NOT contain the original drive
        # letter or absolute prefix any more.
        self.assertNotIn("D:", rewritten or "")
        self.assertFalse(
            file_usage.is_blender_path_absolute(rewritten or ""),
            "Rewritten path must be blendfile-relative, not absolute.",
        )

    def test_absolute_no_rule_fallback_unc_path(self) -> None:
        """Issue #92905: UNC path falls back into the pack without crashing."""
        pack_source_root = PureWindowsPath(r"A:\flamenco\jobs\062")
        blend_dir_in_pack = pack_source_root / "shots"
        unc_abs = PureWindowsPath(r"\\studio\share\textures\concrete.exr")

        rewritten = path_rewriting._compute_rewritten_path(
            blender_path=str(unc_abs),
            abs_path=unc_abs,
            rewrite_rules={},
            pack_source_root=pack_source_root,
            blend_dir_in_pack=blend_dir_in_pack,
        )

        # The UNC anchor (`\\studio\share`) is stripped; the remaining
        # path is relocated under `_outside_project/`, all within the pack.
        self.assertEqual(
            "//../_outside_project/textures/concrete.exr",
            rewritten,
        )

    def test_absolute_no_rule_fallback_in_pack(self) -> None:
        """Issue #92905: absolute path that lives INSIDE the pack stays put.

        Blender sometimes stores an asset's location as an absolute string
        in the blend file even when the file is inside the project root
        (e.g. an image dropped from the same folder as the .blend). The
        dep tracer correctly skips building a rewrite rule for such
        in-project assets, but the rewriter still has to produce a valid
        ``//``-relative output. Before the fix, the fallback unconditionally
        relocated the asset under ``_outside_project/`` even when the file
        was already inside the pack -- making the pack reference a
        non-existent file.

        After the fix, the rewriter detects the in-pack case and emits a
        ``//``-relative path pointing at the file's actual location inside
        the pack, without the ``_outside_project/`` indirection.
        """
        # Asset lives in the same directory as the blend file, but the
        # blend file stores it as an absolute path.
        in_pack_abs = self.blend_dir_in_pack / "20260310_124549.jpg"

        rewritten = path_rewriting._compute_rewritten_path(
            blender_path=str(in_pack_abs),
            abs_path=in_pack_abs,
            rewrite_rules={},
            pack_source_root=self.pack_source_root,
            blend_dir_in_pack=self.blend_dir_in_pack,
        )

        # The rewritten path is relative to the blend file (just the
        # filename in this case) and does NOT detour through
        # ``_outside_project/``.
        self.assertEqual("//20260310_124549.jpg", rewritten)
        self.assertNotIn("_outside_project", rewritten or "")

    def test_absolute_no_rule_fallback_in_pack_subdir(self) -> None:
        """Same as ``..._in_pack`` but the asset is in a sub-directory."""
        in_pack_abs = self.pack_source_root / "textures/concrete.exr"

        rewritten = path_rewriting._compute_rewritten_path(
            blender_path=str(in_pack_abs),
            abs_path=in_pack_abs,
            rewrite_rules={},
            pack_source_root=self.pack_source_root,
            blend_dir_in_pack=self.blend_dir_in_pack,
        )

        # Walk up from blend_dir_in_pack to pack_source_root, then down
        # into the texture directory -- no `_outside_project/` indirection.
        self.assertEqual("//../../../textures/concrete.exr", rewritten)
        self.assertNotIn("_outside_project", rewritten or "")
