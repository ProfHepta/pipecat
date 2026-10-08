import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from hepta_voice.tool_broker import validate,COMMAND
@pytest.mark.parametrize('name',['send_sms','dial','answer','trade','shell','read_file','telephone_status; touch /tmp/bad'])
def test_no_other_tools(name):
    with pytest.raises(ValueError):validate({'id':'test_0001','name':name,'arguments':{}})
@pytest.mark.parametrize('arguments',[[],None,{'command':'id'},{'target':'other-host'},True])
def test_no_command_or_target_injection(arguments):
    with pytest.raises(ValueError):validate({'id':'test_0001','name':'telephone_status','arguments':arguments})
def test_only_fixed_readonly_command():
    assert validate({'id':'test_0001','name':'telephone_status','arguments':{}})=='test_0001'
    assert COMMAND[-3:]==('/usr/bin/python3','/opt/pocket4-telephony/call-audio-watch.py','--inspect')
    assert 'StrictHostKeyChecking=yes' in COMMAND
