# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Data models used by the path rewriting and its background process."""

import dataclasses
import enum
import functools
from pathlib import Path, PurePath
from typing import Any, Self

import cattrs
import cattrs.preconf.json

from blender_asset_tracer.type_aliases import RewriteRules

__all__ = (
    "PipeMessage",
    "PipeMsgType",
    "RewriteRequest",
)


@dataclasses.dataclass(frozen=True)
class RewriteRequest:
    blendfile: Path
    # The path of this blendfile in the pack, relative to the pack's root:
    relpath_in_pack: PurePath
    rewrite_rules: RewriteRules = dataclasses.field(hash=False, compare=False)
    save_to: Path


class PipeMsgType(enum.Enum):
    QUEUE_REWRITE = "queue"
    """Payload: RewriteRequest"""

    SHUTDOWN = "shutdown"
    """Payload: None"""

    REPORT_START = "report-start"
    """Payload: RewriteRequest"""

    REPORT_DONE = "report-done"
    """Payload: RewriteRequest"""

    REPORT_ERROR = "report-error"
    """Payload: (RewriteRequest, error message: str)"""


type Serialized = tuple[tuple[str, Any], ...]


@dataclasses.dataclass
class PipeMessage:
    """Message class for communicating between processes.

    Instances of this class are converted to/from dictionaries with cattrs.
    The normal approach is to have the Python stdlib use the pickle protocol
    to (un)serialize the messages. That is not suitable for BAT, though, as
    that is meant to be run from a Blender add-on, which must take actions to
    prevent cross-contamination between add-ons, and thus the dependencies of
    one add-on should not be importable by other add-ons (and thus, in general,
    other Python code). This makes pickling impossible, as that needs to be
    able to import the module that contains the pickled types.
    """

    msgtype: PipeMsgType
    payload: None | RewriteRequest | tuple[RewriteRequest, str]

    def serialize(self) -> Serialized:
        """Convert a PipeMessage to something that can be pickled."""
        _converter = _cattrs_converter()
        return tuple(_converter.unstructure(self).items())

    @classmethod
    def unserialize(cls, serialized: Serialized) -> Self:
        """Unserializes a serialized PipeMessage."""
        as_dict = dict(serialized)
        _converter = _cattrs_converter()
        msg = _converter.structure(as_dict, cls)
        assert msg is not None
        return msg


@functools.lru_cache(maxsize=1)
def _cattrs_converter() -> cattrs.Converter:
    converter = cattrs.preconf.json.JsonConverter()

    # Conversion from/to PurePath.
    @converter.register_unstructure_hook
    def unstructure_purepath(value: PurePath) -> str:
        return str(value)

    @converter.register_structure_hook
    def structure_purepath(value: str, _: Any) -> PurePath:
        return PurePath(value)

    # Conversion of PipeMessage.payload:
    @converter.register_structure_hook
    def structure_msg_payload(
        value: None | dict[str, Any] | list[Any], _: Any
    ) -> None | RewriteRequest | tuple[RewriteRequest, str]:
        match value:
            case None:
                return None
            case dict():
                return converter.structure(value, RewriteRequest)
            case list():
                return converter.structure(value, tuple[RewriteRequest, str])
        raise NotImplementedError(f"for type {type(value)}")

    return converter
