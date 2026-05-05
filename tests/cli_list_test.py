# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the ``bat list`` CLI subcommand's tree formatter."""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from blender_asset_tracer import file_usage
from blender_asset_tracer.cli import list_deps

from .file_usage_test import load_blendfile

_my_dir = Path(__file__).resolve().parent
blendfiles = _my_dir / "blendfiles"


class PrintFileTreeTest(unittest.TestCase):
    """Tests for `list_deps._print_file_tree`."""

    def tearDown(self) -> None:
        file_usage.cache_clear()

    def _capture_tree(self, deps_repo: file_usage.FileDependencyRepository) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            list_deps._print_file_tree(deps_repo)
        return buf.getvalue()

    def test_leaf_assets_are_not_duplicated(self) -> None:
        """Issue #92905 follow-up: ``bat list`` printed leaf assets twice.

        The reporter's ``bug_test.blend`` references three images via
        absolute paths. ``bat list`` showed each image both nested under
        the blend file (correct) AND again as a standalone top-level
        entry (wrong). The second occurrence was caused by the loop
        printing every dep that is referenced by *anyone* — but a leaf
        image with no outgoing dependencies has nothing useful to show.
        """
        infile = blendfiles / "bug_test_92905.blend"
        load_blendfile(infile)

        deps_repo = file_usage.dependencies_of_current_blendfile(infile.parent)
        output = self._capture_tree(deps_repo)
        lines = [line.rstrip() for line in output.splitlines() if line.strip()]

        # Exactly one line must be the blend file itself (top-level).
        self.assertEqual(
            ["bug_test_92905.blend"],
            [line for line in lines if not line.startswith(" ")
             and line == "bug_test_92905.blend"],
            msg=f"expected blend file once at top level, got:\n{output}",
        )

        # Every other top-level (non-indented) entry must also reference
        # something — i.e. it must have its own indented children. A
        # standalone top-level leaf is the duplication bug.
        top_level = [line for line in lines if not line.startswith(" ")]

        # Reconstruct (top_level_entry, children_count) by walking lines.
        children_count: dict[str, int] = {}
        current: str | None = None
        for line in lines:
            if line.startswith("    "):
                if current is not None:
                    children_count[current] = children_count.get(current, 0) + 1
            else:
                current = line
                children_count.setdefault(current, 0)

        for entry in top_level:
            self.assertGreater(
                children_count.get(entry, 0),
                0,
                msg=(
                    f"top-level entry {entry!r} has no children, which "
                    f"means it's a leaf asset that should have only been "
                    f"shown nested under its user. Full output:\n{output}"
                ),
            )

    def test_linked_blend_with_textures_shown_nested_only(self) -> None:
        """A linked .blend with its own textures shows up as a sub-tree.

        The textures must appear nested under the linked .blend (where
        they are used) and NOT as standalone top-level entries.
        """
        # `scene.blend` links `material_textures.blend`, which in turn
        # references texture images.
        root = blendfiles / "root"
        infile = root / "scene.blend"
        load_blendfile(infile)

        deps_repo = file_usage.dependencies_of_current_blendfile(root)
        output = self._capture_tree(deps_repo)
        lines = [line.rstrip() for line in output.splitlines() if line.strip()]

        top_level = [line for line in lines if not line.startswith(" ")]

        # Every top-level entry must end in ``.blend`` (only blend files
        # reference other files in this project; textures are leaves).
        for entry in top_level:
            self.assertTrue(
                entry.endswith(".blend"),
                msg=(
                    f"non-blend top-level entry {entry!r} would mean a "
                    f"leaf asset is being duplicated. Full output:\n{output}"
                ),
            )


if __name__ == "__main__":
    unittest.main()
