import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import pytest
from hepta_voice.control import Epoch,Ledger,Rejected,split_clause,checked_id

def test_interrupt_invalidates_late_audio():
    e=Epoch(); first,stop=e.advance(); assert e.valid(first)
    second,_=e.advance(); assert stop.is_set(); assert not e.valid(first); assert e.valid(second)

def test_duplicate_same_request_is_not_reexecuted(tmp_path):
    l=Ledger(tmp_path/'x.db');assert not l.reserve('request_0001','speech',{'text':'hello'})['duplicate']
    assert l.reserve('request_0001','speech',{'text':'hello'})['duplicate']

def test_duplicate_conflicting_payload(tmp_path):
    l=Ledger(tmp_path/'x.db');l.reserve('request_0001','speech','a')
    with pytest.raises(Rejected):l.reserve('request_0001','speech','b')

def test_crash_pending_becomes_unknown(tmp_path):
    p=tmp_path/'x.db';l=Ledger(p);l.reserve('request_0001','speech','a');l.close()
    l=Ledger(p);assert l.reserve('request_0001','speech','a')['status']=='unknown'

def test_tool_effect_durable_and_not_duplicated(tmp_path):
    p=tmp_path/'x.db';l=Ledger(p);assert l.local_note('request_0001','仅本地测试')['status']=='saved_locally';l.close()
    l=Ledger(p);assert l.local_note('request_0001','仅本地测试')['duplicate'];assert l.count_notes()==1

def test_tool_conflict_no_second_effect(tmp_path):
    l=Ledger(tmp_path/'x.db');l.local_note('request_0001','a')
    with pytest.raises(Rejected):l.local_note('request_0001','b')
    assert l.count_notes()==1

@pytest.mark.parametrize('bad',['', '../escape','a'*100,3,None])
def test_request_ids_rejected(bad):
    with pytest.raises(Rejected):checked_id(bad)

def test_finish_preserves_terminal_state(tmp_path):
    l=Ledger(tmp_path/'x.db');l.reserve('request_0001','speech','a');l.finish('request_0001','interrupted');l.finish('request_0001','done')
    assert l.reserve('request_0001','speech','a')['status']=='interrupted'

def test_clause_streaming():
    assert split_clause('您好，我是本地助理。还有什么')==('您好，我是本地助理。','还有什么')
    assert split_clause('尚未完成')==('','尚未完成')
    assert split_clause('尚未完成',True)==('尚未完成','')

@pytest.mark.parametrize('bad',['',' '*5,'x'*501,None])
def test_invalid_note_has_no_effect(tmp_path,bad):
    l=Ledger(tmp_path/'x.db')
    with pytest.raises(Rejected):l.local_note('request_0001',bad)
    assert l.count_notes()==0
