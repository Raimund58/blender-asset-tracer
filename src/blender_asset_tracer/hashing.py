# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-3.0-or-later

import contextlib
import datetime
import json
import sqlite3
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, Iterator

__all__ = (
    "get_hasher",
    "FileMetaStore",
)

_hash_algorithm = "sha256"

# Storage paths relative to bpy.app.cachedir.
_hash_storage_cache_path = "bat/file_hashes"
_file_meta_cache_path = "bat/file_meta"


def get_hasher() -> Callable[[Path], str]:
    """Return a callable that computes the hash of a file.

    Internally this uses Blender's DiskFileHashService for efficiently cached
    hash computation.
    """

    import bpy  # pyright: ignore[reportMissingImports]

    # For now, this is a library internal to Blender. It was made with BAT in mind
    # though, so once it's seen some production use, it's probably going to be
    # promoted to a public API.
    from _bpy_internal import (  # pyright: ignore[reportMissingImports]
        disk_file_hash_service as dfhs,
    )

    hash_storage_path = Path(bpy.app.cachedir) / _hash_storage_cache_path
    hash_service = dfhs.get_service(hash_storage_path)
    return partial(hash_service.get_hash, hash_algorithm=_hash_algorithm)


# How many days file metadata is retained.
META_RETAIN_DURATION_DAYS = 31

# SQLite busy timeout in seconds.
DB_TIMEOUT_SEC = 5

DB_SCHEMA_VERSION = 1
CREATE_SCHEMA_V1 = """
BEGIN EXCLUSIVE;
CREATE TABLE IF NOT EXISTS file_meta (
    file_hash TEXT NOT NULL PRIMARY KEY,
    last_used DATETIME NOT NULL,
    meta jsonb NOT NULL
);
COMMIT;
"""

# Set to True to print all SQL queries.
_DEBUG_QUERIES = False

type JSONDict = dict[str, Any]


class FileMetaStore:
    _hasher: Callable[[Path], str]

    _dbfile_path: Path  # Path of the .sqlite file to use.
    _db_conn: sqlite3.Connection | None = None

    def __init__(self) -> None:
        import bpy  # pyright: ignore[reportMissingImports]

        self._hasher = get_hasher()

        storage_path = Path(bpy.app.cachedir) / _file_meta_cache_path
        self._dbfile_path = storage_path.with_name(
            "{}_v{}.sqlite".format(storage_path.stem, DB_SCHEMA_VERSION)
        )
        self._db_conn = None

    def open(self) -> None:
        """Prepare the FileMetaStore for use.

        Create the directory structure & database file, and ensure the schema is as expected.
        """
        import sqlite3

        self._dbfile_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_conn = sqlite3.connect(
            self._dbfile_path,
            timeout=DB_TIMEOUT_SEC,
            isolation_level=None,
        )
        if _DEBUG_QUERIES:

            def callback_rw(query: str) -> None:
                query = query.replace("\n", "\n    ")
                print(f"SQL/RW: {query}")

            self._db_conn.set_trace_callback(callback_rw)
        self._execute_pragmas_on_connect(self._db_conn)

        # Assumption: if the table exists, it should be in the right shape. If
        # that's not the case, the DB_SCHEMA_VERSION class variable should have
        # been incremented, and we'd be accessing another database file.
        #
        # This does not use our _transaction_rw() function, as the executescript()
        # function expects the transaction management to be included in the script
        # itself. It will auto-commit any already-opened transaction, before
        # running the script.
        self._db_conn.executescript(CREATE_SCHEMA_V1)

    def close(self) -> None:
        """Close the database connection."""
        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None

    def get_metadata(self, path: Path) -> JSONDict | None:
        hash = self._hasher(path)

        with self._transaction() as db:
            cursor = db.execute("SELECT meta FROM file_meta WHERE file_hash=?", (hash,))
            # The uniqueness constraints ensure there is at most one row.
            row = cursor.fetchone()

        self._autoclean()

        if row is None:
            return None
        return json.loads(row[0])

    def store_metadata(self, path: Path, metadata: JSONDict) -> None:
        metadata_as_json = json.dumps(metadata)
        file_hash = self._hasher(path)
        now = self._now_string()

        with self._transaction() as db:
            db.execute(
                "INSERT INTO file_meta (file_hash, last_used, meta) VALUES (:file_hash, :last_used, :meta) "
                + "ON CONFLICT DO UPDATE SET last_used=:last_used, meta=:meta",
                dict(file_hash=file_hash, last_used=now, meta=metadata_as_json),
            )

        self._autoclean()

    def __repr__(self) -> str:
        return "{!s}()".format(self.__class__.__qualname__)

    def remove_older_than(self, *, days: int) -> None:
        """Remove all entries that are older than this many days."""
        older_than = self._now() - datetime.timedelta(days=days)

        with self._transaction() as db:
            db.execute(
                "DELETE FROM file_meta WHERE last_used<?", (older_than.isoformat(),)
            )

    def _autoclean(self) -> None:
        self.remove_older_than(days=META_RETAIN_DURATION_DAYS)

    def _now(self) -> datetime.datetime:
        """Current time, as UTC, in a timezone-aware object."""
        return datetime.datetime.now(tz=datetime.timezone.utc)

    def _now_string(self) -> str:
        """Current time, as UTC, in ISO 6801 notation."""
        return self._now().isoformat()

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Start a read-write transaction.

        The transaction is rolled back when an exception is raised, and
        committed otherwise.
        """
        assert self._db_conn is not None, "Open the back-end before trying to use it"

        self._db_conn.execute("BEGIN EXCLUSIVE")
        try:
            yield self._db_conn
        except BaseException:
            self._db_conn.rollback()
            raise
        else:
            self._db_conn.commit()

    @staticmethod
    def _execute_pragmas_on_connect(db_conn: sqlite3.Connection) -> None:
        db_conn.execute("PRAGMA busy_timeout = {:d}".format(DB_TIMEOUT_SEC * 1000))
        db_conn.execute("PRAGMA foreign_keys = 1")
        db_conn.execute("PRAGMA journal_mode = WAL")
        db_conn.execute("PRAGMA synchronous = normal")
