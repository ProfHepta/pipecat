"""Filesystem-only endpoint checks; all credentials are synthetic test data."""
import socket
from pathlib import Path

import pytest
from hepta_voice.endpoint_attestation import validate_local_endpoint_files


@pytest.fixture
def artifacts(tmp_path):
    tmp_path.chmod(0o700)
    key = tmp_path / 'llama.key'
    key.write_text('test-only-' + '3e' * 32)
    key.chmod(0o600)
    sock_path = tmp_path / 'llama.sock'
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(sock_path))
    sock_path.chmod(0o600)
    yield tmp_path
    sock.close()


def test_private_regular_key_and_socket_accepted(artifacts):
    validate_local_endpoint_files(artifacts)


def test_group_readable_key_is_rejected(artifacts):
    (artifacts / 'llama.key').chmod(0o640)
    with pytest.raises(RuntimeError, match='engine_key_permissions'):
        validate_local_endpoint_files(artifacts)


def test_group_readable_socket_is_rejected(artifacts):
    (artifacts / 'llama.sock').chmod(0o660)
    with pytest.raises(RuntimeError, match='engine_socket_permissions'):
        validate_local_endpoint_files(artifacts)


def test_world_accessible_state_dir_is_rejected(artifacts):
    artifacts.chmod(0o755)
    with pytest.raises(RuntimeError, match='engine_state_directory_permissions'):
        validate_local_endpoint_files(artifacts)


def test_linked_key_is_rejected(artifacts):
    key = artifacts / 'llama.key'
    key.rename(artifacts / 'actual.key')
    key.symlink_to(artifacts / 'actual.key')
    with pytest.raises(RuntimeError, match='engine_key_identity_invalid'):
        validate_local_endpoint_files(artifacts)


def test_missing_socket_is_rejected(artifacts):
    (artifacts / 'llama.sock').unlink()
    with pytest.raises(FileNotFoundError):
        validate_local_endpoint_files(artifacts)


def test_regular_file_instead_of_socket_is_rejected(artifacts):
    (artifacts / 'llama.sock').unlink()
    (artifacts / 'llama.sock').write_text('not a socket')
    with pytest.raises(RuntimeError, match='engine_socket_type_or_owner_invalid'):
        validate_local_endpoint_files(artifacts)


def test_empty_key_is_rejected(artifacts):
    (artifacts / 'llama.key').write_text('')
    with pytest.raises(RuntimeError, match='engine_key_length_invalid'):
        validate_local_endpoint_files(artifacts)
