"""Fail-closed checks on local authentication and Unix forwarding artifacts.

Never fetches/copies credentials or opens a remote connection. The only allowed
endpoint is the private state directory mounted into the network-none sandbox.
"""
import os
import stat
from pathlib import Path


def validate_local_endpoint_files(state: Path) -> None:
    state = Path(state)
    directory = state.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid():
        raise RuntimeError('engine_state_directory_invalid')
    if directory.st_mode & 0o077:
        raise RuntimeError('engine_state_directory_permissions')

    key = state / 'llama.key'
    socket_path = state / 'llama.sock'
    key_mode = key.lstat()
    sock_mode = socket_path.lstat()
    if not stat.S_ISREG(key_mode.st_mode) or key_mode.st_uid != os.getuid():
        raise RuntimeError('engine_key_identity_invalid')
    if key_mode.st_mode & 0o077 or not key_mode.st_mode & 0o400:
        raise RuntimeError('engine_key_permissions')
    if not stat.S_ISSOCK(sock_mode.st_mode) or sock_mode.st_uid != os.getuid():
        raise RuntimeError('engine_socket_type_or_owner_invalid')
    if sock_mode.st_mode & 0o077:
        raise RuntimeError('engine_socket_permissions')
    # Contents are not returned or recorded. Size bounds reject empty or
    # malformed credentials without risking accidental logging.
    if not 32 <= len(key.read_text().strip()) <= 256:
        raise RuntimeError('engine_key_length_invalid')
