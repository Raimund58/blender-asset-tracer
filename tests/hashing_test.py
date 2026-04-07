# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import shutil
import unittest
from pathlib import Path

import bpy

from blender_asset_tracer import hashing


class FileMetaTest(unittest.TestCase):
    maxDiff = None
    temp_dir: Path
    file_path: Path

    store: hashing.FileMetaStore | None

    def setUp(self) -> None:
        self.temp_dir = Path(bpy.app.tempdir) / "abs-path-test"
        self.temp_dir.mkdir(exist_ok=True, parents=True)

        self.file_path = self.temp_dir / "some_file.txt"
        self.file_path.write_text("😻 I like cats 😻")

        self.store = None

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

        if self.store is not None:
            self.store.close()

    def test_store_meta(self) -> None:
        self.store = hashing.FileMetaStore()
        self.store.open()

        metadata = {"cat": "🐈"}

        self.store.store_metadata(self.file_path, metadata)
        retrieved = self.store.get_metadata(self.file_path)
        self.assertEqual(metadata, retrieved)

        self.store.close()
        self.store.open()

        retrieved = self.store.get_metadata(self.file_path)
        self.assertEqual(metadata, retrieved)

    def test_get_metadata_after_reopening(self) -> None:
        self.store = hashing.FileMetaStore()

        metadata = {"cat": "🐈"}

        self.store.open()
        self.store.store_metadata(self.file_path, metadata)
        self.store.close()

        self.store.open()
        retrieved = self.store.get_metadata(self.file_path)
        self.assertEqual(metadata, retrieved)

    def test_modify_file(self) -> None:
        self.store = hashing.FileMetaStore()

        metadata = {"cat": "🐈"}

        self.store.open()
        self.store.store_metadata(self.file_path, metadata)

        # Modify the file
        self.file_path.write_text("Lasksa & Quercus 😻")

        retrieved = self.store.get_metadata(self.file_path)
        self.assertIsNone(retrieved)

        # Restore the file to its original contents.
        self.file_path.write_text("😻 I like cats 😻")
        retrieved = self.store.get_metadata(self.file_path)
        self.assertEqual(metadata, retrieved)

    def test_remove_older_than(self) -> None:
        self.store = hashing.FileMetaStore()

        metadata = {"cat": "🐈"}

        self.store.open()
        self.store.store_metadata(self.file_path, metadata)

        # Remove everything, because everything is older than 1 day in the future.
        self.store.remove_older_than(days=-1)

        retrieved = self.store.get_metadata(self.file_path)
        self.assertIsNone(retrieved)
