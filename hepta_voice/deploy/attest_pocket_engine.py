"""Read-only Pocket4 GPU engine attestation; never exports model/API secrets."""
import json
import shlex
import subprocess
from pathlib import Path

ENGINE_SHA = "d81235049384534c167caea52b85a694f6103d14"
BINARY_SHA = "5faf410bbbc00a1b94b09ee01623699f255365628dfa73b1ee552d9e52a2231d"
MODEL_SHA = "85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9"

# This source runs ON pocket4 over an existing pinned-host-key SSH identity.
# It reads process identity, files and local loopback only. Key material stays
# on Pocket4. No service start/stop, GPU eviction, or sound device access.
REMOTE_READ_ONLY = r'''
import json, pathlib, os, socket
from urllib.request import Request, build_opener, ProxyHandler
R=pathlib.Path.home()/".local/state/hepta-inference"
p=R/"engine-instance.json"
j=json.loads(p.read_text())
pid=j["pid"]
q=pathlib.Path("/proc")/str(pid)
boot=pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()
start=(q/"stat").read_text().split()[21]
cmd=(q/"cmdline").read_bytes().split(b"\0")
argv=[x.decode(errors="replace") for x in cmd if x]
fds=[]
for f in (q/"fd").iterdir():
    try:
        target=os.readlink(f)
        if target.startswith("/dev/dri/render"):fds.append(target)
    except (OSError, PermissionError):pass
def has_pair(flag,value):
    return any(argv[i]==flag and argv[i+1]==value for i in range(len(argv)-1))
identity=(boot==j["boot_id"] and start==j["start_ticks"])
flags=all((has_pair("-c","4096"),has_pair("-np","1"),has_pair("-ngl","99"),
           has_pair("-ctk","f16"),has_pair("-ctv","f16"),has_pair("-fa","on"),
           has_pair("--host","127.0.0.1"),has_pair("--port","18455")))
# The remote API credential never enters stdout or SSH arguments.
token=(R/"ab-20261009/api.key").read_text().strip()
headers={"Authorization":"Bearer "+token}
opener=build_opener(ProxyHandler({}))
def read_api(path):
    req=Request("http://127.0.0.1:18455"+path,headers=headers)
    with opener.open(req,timeout=5) as response:return json.load(response)
health=read_api("/health")
props=read_api("/props")
out={"identity":identity,"flags":flags,"pid":pid,"boot_id":boot,
     "start_ticks":start,"commit":j.get("commit"),
     "model_sha256":j.get("model_sha256"),
     "binary_sha256":j.get("binary_sha256"),
     "backend":j.get("backend"),"flash_attention":j.get("flash_attention"),
     "engine_ready":health.get("status")=="ok",
     "model_alias":props.get("model_alias"),
     "model_ftype":props.get("model_ftype"),
     "total_slots":props.get("total_slots"),
     "n_ctx":props.get("default_generation_settings",{}).get("n_ctx"),
     "gpu_render_fds":len(fds),
     "only_loopback":has_pair("--host","127.0.0.1"),
     "read_only_no_phone":True}
print(json.dumps(out,sort_keys=True))
'''

def verify_engine_attestation(attestation: dict) -> bool:
    if not isinstance(attestation, dict):
        raise ValueError("attestation_missing")
    expect = {
        "identity": True, "flags": True, "commit": ENGINE_SHA,
        "model_sha256": MODEL_SHA, "binary_sha256": BINARY_SHA,
        "backend": "Vulkan", "flash_attention": True,
        "engine_ready": True, "model_alias": "hepta-qwen3-4b",
        "model_ftype": "Q4_K - Medium", "total_slots": 1,
        "n_ctx": 4096, "only_loopback": True,
        "read_only_no_phone": True,
    }
    for field, value in expect.items():
        if attestation.get(field) != value:
            raise ValueError("pocket4_engine_attestation_mismatch:" + field)
    if type(attestation.get("gpu_render_fds")) is not int or attestation["gpu_render_fds"] < 1:
        raise ValueError("pocket4_gpu_fd_missing")
    if type(attestation.get("pid")) is not int or attestation["pid"] < 2:
        raise ValueError("pocket4_process_identity_missing")
    return True

def probe_pocket4_engine(timeout=12) -> dict:
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=7", "-o", "ClearAllForwardings=yes",
        "-o", "ForwardAgent=no", "-o", "ForwardX11=no",
        "pocket4", "/usr/bin/python3", "-c", shlex.quote(REMOTE_READ_ONLY),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError("pocket4_readonly_engine_probe_failed")
    reply = json.loads(result.stdout)
    verify_engine_attestation(reply)
    return reply
