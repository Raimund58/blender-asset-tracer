# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from pathlib import Path

from . import path_clustering


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
