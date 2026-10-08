"""Install local units without enabling inference or requesting additional privileges."""
import os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DATA=Path(os.environ.get('HEPTA_VOICE_DATA',str(Path.home()/'.local/share/hepta-pipecat')))
UNITS=Path.home()/'.config/systemd/user';UNITS.mkdir(parents=True,exist_ok=True)
(UNITS/'hepta-pipecat.service').write_text(f'''[Unit]
Description=Hepta Pipecat CPU-only offline laboratory
StartLimitIntervalSec=120
StartLimitBurst=3
Wants=hepta-pipecat-tools.service
After=hepta-pipecat-tools.service
[Service]
Type=simple
WorkingDirectory={ROOT}
Environment=HEPTA_VOICE_DATA={DATA}
ExecStart={ROOT}/hepta_voice/ops/run-cpu.sh
ExecStop=/usr/bin/docker stop -t 10 hepta-pipecat-lab
TimeoutStopSec=20
Restart=no
[Install]
WantedBy=default.target
''')
(UNITS/'hepta-pipecat-tools.service').write_text(f'''[Unit]
Description=Hepta Pipecat fixed read-only phone diagnostic
[Service]
Type=simple
WorkingDirectory={ROOT}
Environment=HEPTA_VOICE_DATA={DATA}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={DATA}/venv/bin/python -m hepta_voice.tool_broker
UMask=0077
NoNewPrivileges=true
MemoryMax=256M
CPUQuota=25%
TasksMax=24
Restart=on-failure
RestartSec=5
[Install]
WantedBy=default.target
''')
env={**os.environ,'XDG_RUNTIME_DIR':f'/run/user/{os.getuid()}'}
subprocess.run(['systemctl','--user','daemon-reload'],env=env,check=True)
print('units installed; inference not enabled')
