"""Pocket4-only read-only telephone status broker, Python stdlib only.

No SSH, modem control, SMS, dial, arbitrary command or write tool.
It runs under alex's unprivileged user service. Audio is inspected only.
"""
import datetime
import fcntl
import json
import os
import re
import signal
import socket
import socketserver
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from hepta_voice.config import STATE

COMMAND = ("/usr/bin/python3", "/opt/pocket4-telephony/call-audio-watch.py", "--inspect")
MAX_REQUEST = 2048


def validate(payload):
    if type(payload) is not dict or set(payload) != {"id", "name", "arguments"}:
        raise ValueError("invalid_envelope")
    rid = payload["id"]
    if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,96}", rid):
        raise ValueError("invalid_id")
    if payload["name"] != "telephone_status":
        raise ValueError("tool_not_allowed")
    if type(payload["arguments"]) is not dict or payload["arguments"]:
        raise ValueError("arguments_not_allowed")
    return rid


def inspect():
    result = subprocess.run(COMMAND, capture_output=True, timeout=8, check=True)
    if len(result.stdout) > 65536:
        raise RuntimeError("inspection_too_large")
    item = json.loads(result.stdout)
    count = item.get("active_call_count")
    if item.get("code") != "READ_ONLY_AUDIO_READY":
        raise RuntimeError("audio_not_ready")
    if type(count) is not int or not 0 <= count <= 1:
        raise RuntimeError("active_call_invalid")
    if item.get("loopbacks_started") is not False:
        raise RuntimeError("inspection_altered_audio")
    return {
        "target": "pocket4", "physical_audio_ready": True,
        "active_call_count": count,
        "real_incoming_call_verified": False,
        "remote_audibility_verified": False,
        "phone_control_performed": False,
        "source": "existing call-audio-watch.py --inspect",
    }


class FixedHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def reply(self, code, item):
        raw = json.dumps(item, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"ready": True, "allowed_tools": ["telephone_status"], "write_tools": []})
        else:
            self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/call":
            self.reply(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if not 1 <= length <= MAX_REQUEST:
                raise ValueError("request_body_limit")
            payload = json.loads(self.rfile.read(length))
            rid = validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError):
            self.reply(400, {"error": "tool_not_allowed_or_invalid"})
            return
        try:
            result = inspect()
            self.reply(200, {
                "id": rid, "name": "telephone_status", "status": "ok",
                "read_only": True,
                "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "result": result,
            })
        except (RuntimeError, subprocess.TimeoutExpired, subprocess.CalledProcessError,
                json.JSONDecodeError, OSError):
            self.reply(503, {"id": rid, "status": "failed", "result": None})


class PocketBroker(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False

    def verify_request(self, request, client_address):
        try:
            import struct
            _, uid, _ = struct.unpack(
                "3i", request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            return uid == os.getuid()
        except OSError:
            return False


def main():
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    lock = os.open(STATE / "tools-owner.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sock = STATE / "tools.sock"
    if sock.exists():
        if not stat.S_ISSOCK(sock.lstat().st_mode) or sock.lstat().st_uid != os.getuid():
            raise RuntimeError("foreign_tool_socket")
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(1)
            try:
                probe.connect(str(sock))
            except ConnectionRefusedError:
                sock.unlink()
            else:
                raise RuntimeError("tool_socket_already_serving")

    server = PocketBroker(str(sock), FixedHandler)
    sock.chmod(0o600)
    inode = sock.stat().st_ino

    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print("pocket_telephone_readonly_broker_ready", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        if sock.exists() and sock.lstat().st_ino == inode:
            sock.unlink()
        os.close(lock)


if __name__ == "__main__":
    main()
