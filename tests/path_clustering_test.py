# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
import unittest.mock
from pathlib import Path, PureWindowsPath

from blender_asset_tracer import path_clustering


class PathClusteringTest(unittest.TestCase):
    def test_path_clustering(self) -> None:
        root1 = Path("/studio/_flamenco/jobs/060_0050-lighting-7qbr/pro/assets")
        root2 = Path("/studio/_flamenco/common/assets")

        # The paths are somewhat randomly ordered, to ensure that the clustering
        # algorithm is insensitive to the insertion order.
        paths = [
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

        clusters = path_clustering.build_clusters(paths, min_files_per_cluster=2)
        expected = {
            Path("/local/blender/nodes"): [Path("geometry_nodes_essentials.blend")],
            Path("/studio/_flamenco/common/assets"): [
                Path("maps/watercolor_blended_02.png"),
                Path("maps/ice_shards-vertical_streaks.png"),
                Path("maps/normal_brushstrokes.exr"),
                Path("maps/roughness-watercolor.exr"),
                Path("maps/background_creatures/background_creatures_<UDIM>.tif"),
                Path("brushstroke_tools/styles/maps/oil_paint-grunge.exr"),
                Path("brushstroke_tools/styles/maps/watercolor-soft_bloom.exr"),
                Path("brushstroke_tools/core/maps/canvas-linen_01.exr"),
                Path("nodes/tonemapper.blend"),
            ],
            Path("/studio/_flamenco/jobs/060_0050-lighting-7qbr/pro/assets"): [
                Path("scripts/update_bake_path.blend"),
                Path("nodes/distance_to_silhouette.blend"),
                Path("nodes/background_creatures.blend"),
                Path("nodes/utilities.blend"),
                Path("nodes/background_creatures.blen"),
                Path("nodes/painterly_shading.blend"),
                Path("nodes/compositing.blend"),
                Path("brushstroke_tools/styles/brushstroke_tools-oil_brushes.blend"),
                Path("brushstroke_tools/styles/brushstroke_tools-_brushes.blend"),
                Path("brushstroke_tools/core/brushstroke_tools-resources.blend"),
                Path("fx/tendril_energy.blend"),
            ],
        }

        self.maxDiff = None
        self.assertEqual(expected, clusters)

    def test_cross_anchor_paths_get_separate_clusters(self) -> None:
        """
        Issue #92905 follow-up: when the input paths span multiple
        filesystem anchors (different Windows drives, drive + UNC share,
        ...), there is no shared filesystem prefix. The synthetic root of
        the prefix tree must NOT be promoted to a cluster root, because
        its associated path would be ``Path('.')`` (no anchor, no parts),
        which crashes ``file_usage._shorten_paths`` with
        ``RuntimeError: Could not shorten these paths: [...Path('.')]``.

        Each anchor must form its own top-level cluster instead.
        """
        # PurePath has no `.is_dir()` method; ``add_file_path`` uses it
        # only as an early sanity check. Stub it for these pure-path inputs.
        with unittest.mock.patch.object(
            PureWindowsPath, "is_dir", lambda self: False, create=True
        ):
            # The exact scenario from bug_test.blend: one asset on D:\,
            # one asset on a UNC share. Different anchors, no common
            # prefix beyond ``Path('.')``.
            clusters = path_clustering.build_clusters(
                [
                    PureWindowsPath("D:/tmp/20260310_124549_d.jpg"),
                    PureWindowsPath(
                        r"\\IHM-MH-SRV01/scandaten/Export_dwg_to_OBJ.png"
                    ),
                ],
            )

        # Two clusters, one per anchor; neither is the meaningless
        # ``Path('.')`` cluster.
        self.assertEqual(2, len(clusters))
        for cluster_prefix in clusters.keys():
            self.assertNotEqual(
                Path("."),
                cluster_prefix,
                msg=(
                    f"cluster prefix {cluster_prefix!r} has no path "
                    "components and would crash _shorten_paths"
                ),
            )
            self.assertGreater(
                len(cluster_prefix.parts),
                0,
                msg=f"cluster prefix {cluster_prefix!r} must have at least one part",
            )

    def test_two_drives_get_separate_clusters(self) -> None:
        """
        Two Windows drive letters split into one cluster per drive.
        Regression test for the same root cause as
        ``test_cross_anchor_paths_get_separate_clusters``.
        """
        with unittest.mock.patch.object(
            PureWindowsPath, "is_dir", lambda self: False, create=True
        ):
            clusters = path_clustering.build_clusters(
                [
                    PureWindowsPath("D:/tmp/a.jpg"),
                    PureWindowsPath("E:/other/b.jpg"),
                ],
            )

        self.assertEqual(2, len(clusters))
        for cluster_prefix in clusters.keys():
            self.assertGreater(len(cluster_prefix.parts), 0)
            # Each cluster's prefix must start with one of the original
            # anchors, not ``.``.
            self.assertIn(cluster_prefix.parts[0], ("D:\\", "E:\\"))
