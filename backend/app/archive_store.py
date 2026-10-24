"""Atomic, content-addressed local snapshot publication for manual historical imports.

Not provider authentication, market-data licensing, backup or retention approval.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import stat

_DIGEST = re.compile(r"[0-9a-f]{64}\\Z")


def _verify_existing(directory_fd: int, filename: str, expected: bytes) -> None:
    # O_NONBLOCK ensures a hostile FIFO cannot block before fstat rejects it.
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                 dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != len(expected):
            raise OSError("Historical snapshot is not a regular file of the expected size")
        if stream.read(len(expected) + 1) != expected:
            raise OSError("Historical snapshot bytes do not match")


def publish_verified_snapshot(directory: Path, digest: str, content: bytes) -> None:
    """Publish only complete snapshots; never overwrite or repair existing bytes.

    A private temporary file is fsynced before hard-link publication. The
    content-addressed target is never visible partially written. Existing
    corrupt files fail closed, leaving restoration to an operator.
    """
    if not isinstance(content, bytes) or not 0 < len(content) <= 3_000_000:
        raise OSError("Invalid historical snapshot size")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise OSError("Invalid historical snapshot digest")
    if hashlib.sha256(content).hexdigest() != digest:
        raise OSError("Historical snapshot digest mismatch")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise OSError("Historical archive directory is not a directory")
        filename = digest + ".json"
        try:
            _verify_existing(directory_fd, filename, content)
            return
        except FileNotFoundError:
            pass

        temporary = "." + digest + "." + secrets.token_hex(12) + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory_fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, filename, src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd, follow_symlinks=False)
            except FileExistsError:
                # Another writer won publication. Verify it rather than overwrite.
                pass
            else:
                os.fsync(directory_fd)
            _verify_existing(directory_fd, filename, content)
        finally:
            os.unlink(temporary, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
