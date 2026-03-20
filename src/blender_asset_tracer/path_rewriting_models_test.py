# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import dataclasses
import unittest
from pathlib import Path, PurePath

from . import path_rewriting_models as models


class RewriteRequestHashableTest(unittest.TestCase):
    test_request = models.RewriteRequest(
        blendfile=Path("/tmp/thefile.blend"),
        relpath_in_pack=PurePath("thefile.blend"),
        rewrite_rules={Path("/tmp"): PurePath("/Volumes/tmp")},
        save_to=Path("/tmp/rewritten.blend"),
    )

    def test_hash(self) -> None:
        _ = hash(self.test_request)

    def test_set_member(self) -> None:
        _ = set([self.test_request])

    def test_dict_key(self) -> None:
        _ = {self.test_request: True}


class PathRewritingModelsTest(unittest.TestCase):
    shutdown_msg = models.PipeMessage(
        msgtype=models.PipeMsgType.SHUTDOWN,
        payload=None,
    )
    shutdown_serial = tuple(
        {
            "msgtype": "shutdown",
            "payload": None,
        }.items()
    )

    queue_msg = models.PipeMessage(
        msgtype=models.PipeMsgType.QUEUE_REWRITE,
        payload=models.RewriteRequest(
            Path("/tmp/thefile.blend"),
            PurePath("thefile.blend"),
            {Path("/tmp"): PurePath("/Volumes/tmp")},
            Path("/tmp/rewritten.blend"),
        ),
    )
    queue_serial = tuple(
        {
            "msgtype": "queue",
            "payload": {
                "blendfile": "/tmp/thefile.blend",
                "relpath_in_pack": "thefile.blend",
                "rewrite_rules": {
                    "/tmp": "/Volumes/tmp",
                },
                "save_to": "/tmp/rewritten.blend",
            },
        }.items()
    )

    report_error_msg = models.PipeMessage(
        msgtype=models.PipeMsgType.REPORT_ERROR,
        payload=(
            models.RewriteRequest(
                Path("/tmp/thefile.blend"),
                PurePath("thefile.blend"),
                {Path("/tmp"): PurePath("/Volumes/tmp")},
                Path("/tmp/rewritten.blend"),
            ),
            "something went wrong 🙀",
        ),
    )
    report_error_serial = tuple(
        {
            "msgtype": "report-error",
            "payload": [
                {
                    "blendfile": "/tmp/thefile.blend",
                    "relpath_in_pack": "thefile.blend",
                    "rewrite_rules": {
                        "/tmp": "/Volumes/tmp",
                    },
                    "save_to": "/tmp/rewritten.blend",
                },
                "something went wrong 🙀",
            ],
        }.items()
    )

    def test_roundtrip__empty(self) -> None:
        serialized = self.shutdown_msg.serialize()
        self.assertEqual(self.shutdown_msg, models.PipeMessage.unserialize(serialized))

    def test_roundtrip__rewriterequest(self) -> None:
        serialized = self.queue_msg.serialize()
        self.assertEqual(self.queue_msg, models.PipeMessage.unserialize(serialized))

    def test_roundtrip__tuple(self) -> None:
        serialized = self.shutdown_msg.serialize()
        self.assertEqual(self.shutdown_msg, models.PipeMessage.unserialize(serialized))

    def test_serialize__empty(self) -> None:
        serialized = self.shutdown_msg.serialize()
        self.assertEqual(self.shutdown_serial, serialized)

    def test_serialize__rewriterequest(self) -> None:
        serialized = self.queue_msg.serialize()
        self.assertEqual(self.queue_serial, serialized)

    def test_serialize__tuple(self) -> None:
        serialized = self.report_error_msg.serialize()
        self.assertEqual(self.report_error_serial, serialized)

    def test_unserialize__empty(self) -> None:
        actual_message = models.PipeMessage.unserialize(self.shutdown_serial)
        self.assertEqualMsg(self.shutdown_msg, actual_message)

    def test_unserialize__rewriterequest(self) -> None:
        actual_message = models.PipeMessage.unserialize(self.queue_serial)
        self.assertEqualMsg(self.queue_msg, actual_message)

    def test_unserialize__tuple(self) -> None:
        actual_message = models.PipeMessage.unserialize(self.report_error_serial)
        self.assertEqualMsg(self.report_error_msg, actual_message)

    def assertEqualMsg(
        self,
        expect_message: models.PipeMessage,
        actual_message: models.PipeMessage,
    ) -> None:
        # Pipe the message through dataclasses.asdict() to get nicer diffs.
        self.maxDiff = None
        self.assertEqual(
            dataclasses.asdict(expect_message),
            dataclasses.asdict(actual_message),
        )
