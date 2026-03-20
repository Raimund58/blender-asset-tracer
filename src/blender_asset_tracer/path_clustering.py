# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

__all__ = ("build_clusters",)

type PathCluster = dict[Path, list[Path]]


def build_clusters(
    paths: Iterable[Path],
    min_files_per_cluster: int = 2,
) -> PathCluster:
    """Subdivide the given paths into clusters.

    Returns a dictionary `{prefix: [paths in that prefix]}`.
    """
    root = PrefixTreeNode("")
    for p in paths:
        root.add_file_path(p)
    root.mark_clusters(min_files_per_cluster)
    return root.collect_clusters(Path())


@dataclass(slots=True)
class PrefixTreeNode:
    """Prefix Tree node for filesystem paths.

    Each directory component is a node in the tree. Each node has a
    list of files that are contained in that directory.
    """

    name: str

    # Mapping from node name to the node itself.
    children: dict[str, PrefixTreeNode] = field(default_factory=dict)

    # Full paths ending at this node.
    files: list[Path] = field(default_factory=list)

    # Mark if this node becomes a cluster root.
    is_cluster_root: bool = False

    def add_file_path(self, path: Path) -> None:
        assert not path.is_dir(), "add_path(node, path) should only be called on files"
        assert self.name == "", (
            "add_file_path(path) should only be called on the root node"
        )
        node = self
        for part in path.parent.parts:
            node = node.children.setdefault(part, PrefixTreeNode(part))
        node.files.append(path)

    def collect_clusters(self, prefix: Path) -> PathCluster:
        """Return dict: node path -> list of relative file paths (as Path objects)"""
        clusters: PathCluster = {}
        # The root node has no name, other nodes are all expected to have names.
        cluster_path = prefix / self.name if self.name else prefix

        if self.is_cluster_root:
            rel_files: list[Path] = []
            for file_path in self._collect_all_files():
                try:
                    rel = file_path.relative_to(cluster_path)
                    rel_files.append(rel if rel != Path() else Path(file_path.name))
                except ValueError:
                    rel_files.append(file_path)
            clusters[cluster_path] = rel_files
        else:
            for child in self.children.values():
                clusters.update(child.collect_clusters(cluster_path))

            if self.files:
                clusters.setdefault(cluster_path, [])
                for file_path in self.files:
                    clusters[cluster_path].append(Path(file_path.name))
        return clusters

    def mark_clusters(self, min_files: int) -> int:
        """Mark nodes as cluster roots if subtree has enough files."""
        total_files = len(self.files)
        for child in self.children.values():
            total_files += child.mark_clusters(min_files)
        if total_files >= min_files:
            self.is_cluster_root = True
            # Once a node is a cluster root, don't let its files count towards
            # its parents' file count.
            return 0
        return total_files

    def _collect_all_files(self) -> list[Path]:
        files = list(self.files)
        for child in self.children.values():
            files.extend(child._collect_all_files())
        return files
