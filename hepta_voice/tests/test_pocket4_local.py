"""Pocket4 local-only broker and external engine-key security contract."""
import os
from pathlib import Path
import pytest
from hepta_voice.ops import pocket_local_proxy as proxy
from hepta_voice.ops import pocket_tool_broker as broker
from hepta_voice.endpoint_attestation import validate_local_endpoint_files


def test_local_proxy_is_fixed_to_existing_loopback_engine():
    assert proxy.BACKEND_HOST == '127.0.0.1'
    assert proxy.BACKEND_PORT == 18455
    assert proxy.MAX_CONCURRENT <= 4
    assert proxy.IDLE_SECONDS <= 120


def test_phone_broker_cannot_accept_write_tool():
    valid={'id':'test_pocket_1234','name':'telephone_status','arguments':{}}
    assert broker.validate(valid)=='test_pocket_1234'
    for name in ('send_sms','dial','answer_call','execute','trade','file_write'):
        with pytest.raises(ValueError):broker.validate({**valid,'name':name})
    with pytest.raises(ValueError):broker.validate({**valid,'arguments':{'number':'10000'}})
    with pytest.raises(ValueError):broker.validate({**valid,'command':'sudo'})


def test_broker_inspection_command_is_local_fixed_and_readonly():
    assert broker.COMMAND == ('/usr/bin/python3','/opt/pocket4-telephony/call-audio-watch.py','--inspect')
    assert not any('ssh' in x or 'sudo' in x for x in broker.COMMAND)


def test_externally_stored_key_remains_regular_and_private(tmp_path):
    state=tmp_path/'state';state.mkdir(mode=0o700)
    key=tmp_path/'existing_engine_key';key.write_text('a'*64);key.chmod(0o600)
    import socket
    sock=socket.socket(socket.AF_UNIX)
    sock.bind(str(state/'llama.sock'));(state/'llama.sock').chmod(0o600)
    try:
        validate_local_endpoint_files(state,key_file=key)
        key.chmod(0o640)
        with pytest.raises(RuntimeError,match='engine_key_permissions'):
            validate_local_endpoint_files(state,key_file=key)
    finally:sock.close()


def test_pocket_container_never_requests_public_network_or_gpu():
    code=(Path(__file__).parents[1]/'ops/run-pocket.sh').read_text()
    for required in ('--network none','--userns keep-id','--read-only','--cap-drop ALL','no-new-privileges','--memory 5g','--pids-limit 192'):
        assert required in code
    assert 'HEPTA_VOICE_ENGINE_KEY_FILE' in code
    assert 'sudo ' not in code and '--privileged' not in code
