"""Pocket4 same-host AF_UNIX to 127.0.0.1:18455 relay.

Only a local Unix socket is exposed. The existing llama.cpp process performs
Bearer authentication. This relay never reads or logs model credentials, opens
telephone devices, or connects to external IP addresses.
"""
import asyncio
import fcntl
import os
import signal
import socket
import stat
from pathlib import Path

from hepta_voice.config import STATE

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 18455
IDLE_SECONDS = 120
MAX_CONCURRENT = 4
MAX_CHUNK = 65536


async def relay_stream(source, destination):
    try:
        while True:
            chunk = await asyncio.wait_for(source.read(MAX_CHUNK), IDLE_SECONDS)
            if not chunk:
                break
            destination.write(chunk)
            await asyncio.wait_for(destination.drain(), 10)
    except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, OSError):
        pass
    finally:
        if destination.can_write_eof():
            try:
                destination.write_eof()
            except (ConnectionError, OSError):
                pass


async def main():
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    lock = os.open(STATE / "llama-local-proxy.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path = STATE / "llama.sock"
    if path.exists():
        if not stat.S_ISSOCK(path.lstat().st_mode) or path.lstat().st_uid != os.getuid():
            raise RuntimeError("unexpected_local_proxy_path")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            try:
                probe.connect(str(path))
            except ConnectionRefusedError:
                path.unlink()  # Prior owner is gone, and we hold the owner lock.
            else:
                raise RuntimeError("another_local_proxy_is_listening")

    limit = asyncio.Semaphore(MAX_CONCURRENT)
    stop = asyncio.Event()

    async def accept(reader, writer):
        raw = writer.get_extra_info("socket")
        try:
            _, uid, _ = __import__("struct").unpack(
                "3i", raw.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            if uid != os.getuid():
                return
            async with limit:
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(BACKEND_HOST, BACKEND_PORT), 3
                )
                try:
                    directions = [
                        asyncio.create_task(relay_stream(reader, remote_writer)),
                        asyncio.create_task(relay_stream(remote_reader, writer)),
                    ]
                    done, pending = await asyncio.wait(directions, return_when=asyncio.FIRST_COMPLETED)
                    for job in pending:
                        job.cancel()
                    await asyncio.gather(*directions, return_exceptions=True)
                finally:
                    remote_writer.close()
                    await remote_writer.wait_closed()
        except (OSError, ConnectionError, TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    server = await asyncio.start_unix_server(accept, path=str(path), backlog=16)
    path.chmod(0o600)
    ino = path.stat().st_ino
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    print("hepta_pocket_local_llama_proxy_ready", flush=True)
    try:
        await stop.wait()
    finally:
        server.close()
        await server.wait_closed()
        if path.exists() and path.lstat().st_ino == ino:
            path.unlink()
        os.close(lock)


if __name__ == "__main__":
    asyncio.run(main())
