"""Install Pocket4-only user units, initially disabled.

Never modifies qian-qi, llama engine, ModemManager, existing telephone services,
sudoers, driver or trading processes. Start/enable only after live acceptance.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path("/home/alex/hepta-pipecat-voice")
DATA = Path("/home/alex/.local/share/hepta-pipecat")
UNITS = Path.home() / ".config/systemd/user"


def install():
    if os.getuid() != 1000 or Path.home() != Path("/home/alex"):
        raise RuntimeError("Pocket4 alex user only")
    UNITS.mkdir(parents=True, exist_ok=True)
    definitions = {
        "hepta-pocket-voice-proxy.service": f"""[Unit]
Description=Hepta Pocket4 private llama.cpp AF_UNIX proxy
After=hepta-pocket-llama.service
Requires=hepta-pocket-llama.service
[Service]
Type=simple
WorkingDirectory={ROOT}
Environment=HEPTA_VOICE_DATA={DATA}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 -m hepta_voice.ops.pocket_local_proxy
UMask=0077
NoNewPrivileges=true
MemoryMax=128M
CPUQuota=30%
TasksMax=32
Restart=on-failure
RestartSec=3
[Install]
WantedBy=default.target
""",
        "hepta-pocket-voice-tools.service": f"""[Unit]
Description=Hepta Pocket4 fixed read-only telephone diagnostic
After=pocket4-call-audio.service
[Service]
Type=simple
WorkingDirectory={ROOT}
Environment=HEPTA_VOICE_DATA={DATA}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/python3 -m hepta_voice.ops.pocket_tool_broker
UMask=0077
NoNewPrivileges=true
MemoryMax=192M
CPUQuota=20%
TasksMax=32
Restart=on-failure
RestartSec=3
[Install]
WantedBy=default.target
""",
        "hepta-pocket-voice-agent.service": f"""[Unit]
Description=Hepta Pocket4 isolated local Pipecat telephone laboratory
After=hepta-pocket-llama.service hepta-pocket-voice-proxy.service hepta-pocket-voice-tools.service
Requires=hepta-pocket-llama.service hepta-pocket-voice-proxy.service hepta-pocket-voice-tools.service
StartLimitIntervalSec=180
StartLimitBurst=3
[Service]
Type=simple
WorkingDirectory={ROOT}
Environment=HEPTA_VOICE_DATA={DATA}
ExecStart={ROOT}/hepta_voice/ops/run-pocket.sh
ExecStop=-/usr/bin/podman stop -t 10 hepta-pocket-voice-lab
TimeoutStartSec=100
TimeoutStopSec=20
KillMode=mixed
UMask=0077
MemoryMax=6G
CPUQuota=400%
TasksMax=256
Restart=on-failure
RestartSec=8
[Install]
WantedBy=default.target
""",
    }
    for name, content in definitions.items():
        path = UNITS / name
        if path.exists():
            if path.read_text() != content:
                raise RuntimeError("existing_unit_differs_no_overwrite:" + name)
            continue
        temp = UNITS / (name + ".new")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        temp.replace(path)
    env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, env=env)
    print("pocket_voice_units_installed_disabled", flush=True)


if __name__ == "__main__":
    install()
