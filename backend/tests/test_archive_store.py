"""Offline archive publication regressions; no provider or database access."""
import hashlib
import os
import pytest
from app.archive_store import publish_verified_snapshot

CONTENT = b'{"meta":{"symbol":"XAU/USD"},"values":[]}'
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def test_atomic_publish_is_idempotent_and_private(tmp_path):
    directory = tmp_path / 'archive'
    publish_verified_snapshot(directory, DIGEST, CONTENT)
    target = directory / (DIGEST + '.json')
    assert target.read_bytes() == CONTENT
    assert target.stat().st_mode & 0o077 == 0
    publish_verified_snapshot(directory, DIGEST, CONTENT)
    assert [p.name for p in directory.iterdir()] == [target.name]


def test_rejects_bad_digest_without_creating_archive(tmp_path):
    directory = tmp_path / 'archive'
    for digest in ('../escape', '0'*64, DIGEST.upper(), ''):
        with pytest.raises(OSError):
            publish_verified_snapshot(directory, digest, CONTENT)
    assert not directory.exists()


@pytest.mark.parametrize('kind', ['corrupt', 'symlink', 'directory', 'fifo'])
def test_existing_unsafe_target_fails_closed(tmp_path, kind):
    directory = tmp_path / 'archive'
    directory.mkdir()
    target = directory / (DIGEST + '.json')
    if kind == 'corrupt':
        target.write_bytes(b'corrupt')
    elif kind == 'symlink':
        outside = tmp_path / 'outside'
        outside.write_bytes(CONTENT)
        target.symlink_to(outside)
    elif kind == 'directory':
        target.mkdir()
    else:
        os.mkfifo(target)
    with pytest.raises(OSError):
        publish_verified_snapshot(directory, DIGEST, CONTENT)
    assert len(list(directory.iterdir())) == 1


def test_symlinked_archive_directory_fails_closed(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        publish_verified_snapshot(link, DIGEST, CONTENT)
    assert not list(real.iterdir())


def test_write_failure_does_not_publish_target_or_leave_temporary(tmp_path, monkeypatch):
    directory = tmp_path / 'archive'
    original_link = os.link
    def fail_link(*args, **kwargs):
        raise OSError('synthetic publication failure')
    monkeypatch.setattr(os, 'link', fail_link)
    with pytest.raises(OSError):
        publish_verified_snapshot(directory, DIGEST, CONTENT)
    assert not list(directory.iterdir())
    monkeypatch.setattr(os, 'link', original_link)
    publish_verified_snapshot(directory, DIGEST, CONTENT)


def test_concurrent_publication_keeps_one_exact_snapshot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    directory = tmp_path / 'archive'
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: publish_verified_snapshot(directory, DIGEST, CONTENT), range(24)))
    assert results == [None] * 24
    assert [p.name for p in directory.iterdir()] == [DIGEST + '.json']
    assert (directory / (DIGEST + '.json')).read_bytes() == CONTENT
