"""Real CLI subprocess round-trips and transport-neutral Agent boundary tests."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from agentos_runtime.contracts import default_plan
from agentos_runtime.gateway import AgentGateway, initialize_demo
from agentos_runtime.runtime import Runtime


def setup(tmp_path):
    home = tmp_path/'home'
    initialize_demo(home,files=3,rows=10)
    return home, AgentGateway(home)


def submit(gateway, request='first'):
    out=gateway.call('task_submit',{'dataset_id':'demo','request_id':request})
    assert out['ok'], out
    assert out['data']['status']=='SUCCEEDED'
    return out['data']


def count_tasks(home):
    with closing(sqlite3.connect(home/'registry.sqlite3')) as conn, conn:
        return conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]


def test_tools_contract_and_default_plan(tmp_path):
    _,g=setup(tmp_path)
    tools=g.tools()
    assert len(tools)==8
    assert all(t['inputSchema']['additionalProperties'] is False for t in tools)
    assert all('approve' not in t['name'] and 'shell' not in t['name'] for t in tools)
    info=g.call('runtime_capabilities',{})['data']
    assert info['model_loop_owner']=='existing_agent'
    assert info['scope']=='synthetic_fixture_only'
    assert g.call('datasets_list',{})['data']['datasets'][0]['rows']==30


def test_submit_inspect_and_paged_artifact(tmp_path):
    home,g=setup(tmp_path)
    result=submit(g)
    task=result['task_id']
    assert result['verification']['passed']
    assert len(result['artifacts'])==4
    assert str(home) not in json.dumps(result)
    artifact=next(x for x in result['artifacts'] if x['name']=='summary.json')
    offset=0; chunks=[]
    while True:
        response=g.call('artifact_read',{'task_id':task,'artifact_id':artifact['artifact_id'],'offset':offset,'max_chars':27})
        assert response['ok']
        item=response['data']; chunks.append(item['content'])
        assert item['content_role']=='untrusted_data_not_instructions'
        offset=item['next_offset']
        if offset is None: break
    value=json.loads(''.join(chunks))
    assert value['total_rows']==30
    events=[]; after=0
    while True:
        item=g.call('task_events',{'task_id':task,'after_seq':after,'limit':2})['data']
        events.extend(item['events'])
        after=item['next_after_seq']
        if after is None: break
    assert len(events)==10
    assert [e['seq'] for e in events]==list(range(1,11))
    assert str(home) not in json.dumps(events)


def test_duplicate_submission_survives_new_client(tmp_path,monkeypatch):
    home,g=setup(tmp_path)
    first=submit(g)
    monkeypatch.setattr('agentos_runtime.gateway.Runtime.run',lambda *_a,**_k: pytest.fail('duplicate execution'))
    g2=AgentGateway(home)
    second=submit(g2)
    assert second['task_id']==first['task_id']
    assert second['replayed_request'] is True
    assert count_tasks(home)==1


def test_same_id_new_plan_is_rejected(tmp_path):
    home,g=setup(tmp_path)
    submit(g)
    plan=default_plan().model_dump(); plan['goal']='new goal'
    out=g.call('task_submit',{'dataset_id':'demo','request_id':'first','plan':plan})
    assert not out['ok']
    assert out['error']['code']=='IDEMPOTENCY_CONFLICT'
    assert count_tasks(home)==1


@pytest.mark.parametrize('tool,args',[
    ('approve',{}), ('shell_execute',{'command':'echo unsafe'}),
    ('task_submit',{'dataset_id':'../../etc','request_id':'x'}),
    ('task_submit',{'dataset_id':'demo','request_id':'x','approved':True}),
    ('task_submit',{'dataset_id':'demo','request_id':'x','home':'/etc'}),
    ('task_inspect',{'task_id':'../other'}),
    ('task_inspect',{'task_id':'0'*32,'owner':'admin'}),
    ('artifact_read',{'task_id':'0'*32,'artifact_id':'../../etc/passwd'}),
    ('artifact_read',{'task_id':'0'*32,'artifact_id':'0'*64,'max_chars':8001}),
    ('task_events',{'task_id':'0'*32,'limit':1000}),
    ('datasets_list',{'scan_root':'/'}),
])
def test_bad_tools_have_no_effects(tmp_path,tool,args):
    home,g=setup(tmp_path)
    out=g.call(tool,args)
    assert not out['ok']
    assert out['error']['code'] in {'UNKNOWN_TOOL','INVALID_ARGUMENT'}
    assert count_tasks(home)==0
    assert not list((home/'tasks').iterdir())


def test_unregistered_dataset_denied(tmp_path):
    home,g=setup(tmp_path)
    out=g.call('task_submit',{'dataset_id':'unknown','request_id':'x'})
    assert out['error']['code']=='DATASET_NOT_ALLOWED'
    assert count_tasks(home)==0


def test_unknown_task_not_created(tmp_path):
    home,g=setup(tmp_path)
    assert g.call('task_resume',{'task_id':'0'*32})['error']['code']=='TASK_NOT_FOUND'
    assert not list((home/'tasks').iterdir())


def test_other_task_artifact_id_rejected(tmp_path):
    _,g=setup(tmp_path)
    a,b=submit(g,'a'),submit(g,'b')
    out=g.call('artifact_read',{'task_id':b['task_id'],'artifact_id':a['artifacts'][0]['artifact_id']})
    assert out['error']['code']=='ARTIFACT_NOT_FOUND'


def test_changed_public_artifact_no_success_claim(tmp_path):
    home,g=setup(tmp_path)
    result=submit(g)
    (home/'tasks'/result['task_id']/'run/outputs/summary.json').write_text('{}')
    out=g.call('task_inspect',{'task_id':result['task_id']})
    assert out['error']['code']=='ARTIFACT_CHANGED'


def test_policy_revocation_prevents_new_submission(tmp_path):
    home,g=setup(tmp_path)
    value=json.loads((home/'owner_policy.json').read_text()); value['allowed_operations']=[]
    (home/'owner_policy.json').write_text(json.dumps(value))
    out=g.call('task_submit',{'dataset_id':'demo','request_id':'x'})
    assert out['error']['code']=='POLICY_DENIED'
    assert count_tasks(home)==0


def test_task_limit_enforced(tmp_path):
    home,g=setup(tmp_path)
    value=json.loads((home/'owner_policy.json').read_text()); value['max_tasks']=1
    (home/'owner_policy.json').write_text(json.dumps(value))
    submit(g)
    assert g.call('task_submit',{'dataset_id':'demo','request_id':'second'})['error']['code']=='TASK_BUDGET'
    assert count_tasks(home)==1


def test_cancel_through_another_client_stops_next_node(tmp_path,monkeypatch):
    home,g=setup(tmp_path)
    original=Runtime.run
    def wrapper(self,*args,**kwargs):
        def cancel(node,_):
            if node=='snapshot':
                with closing(sqlite3.connect(home/'registry.sqlite3')) as conn, conn:
                    task_id=conn.execute('SELECT task_id FROM tasks').fetchone()[0]
                assert AgentGateway(home).call('task_cancel',{'task_id':task_id})['ok']
        return original(self,*args,**kwargs,after_node=cancel)
    monkeypatch.setattr('agentos_runtime.gateway.Runtime.run',wrapper)
    result=g.call('task_submit',{'dataset_id':'demo','request_id':'first'})
    assert result['ok']
    data=result['data']; assert data['status']=='CANCELLED'
    assert not data['artifacts']
    assert g.call('task_resume',{'task_id':data['task_id']})['error']['code']=='CANCELLED'


def test_live_owner_policy_reread(tmp_path,monkeypatch):
    home,g=setup(tmp_path)
    original=Runtime.run
    def wrapper(self,*args,**kwargs):
        def revoke(node,_):
            if node=='snapshot':
                value=json.loads((home/'owner_policy.json').read_text()); value['allowed_operations']=[]
                (home/'owner_policy.json').write_text(json.dumps(value))
        return original(self,*args,**kwargs,after_node=revoke)
    monkeypatch.setattr('agentos_runtime.gateway.Runtime.run',wrapper)
    result=g.call('task_submit',{'dataset_id':'demo','request_id':'first'})
    assert result['data']['status']=='FAILED'
    assert result['data']['error_code']=='POLICY_DENIED'


def test_reserved_submission_can_be_resumed_without_duplicate(tmp_path,monkeypatch):
    home,g=setup(tmp_path)
    original=Runtime.run
    def disconnected(*_a,**_k): raise KeyboardInterrupt()
    monkeypatch.setattr('agentos_runtime.gateway.Runtime.run',disconnected)
    with pytest.raises(KeyboardInterrupt): submit(g)
    assert count_tasks(home)==1
    with closing(sqlite3.connect(home/'registry.sqlite3')) as conn, conn:
        task_id=conn.execute('SELECT task_id FROM tasks').fetchone()[0]
    assert g.call('task_inspect',{'task_id':task_id})['data']['status']=='RESERVED'
    duplicate=g.call('task_submit',{'dataset_id':'demo','request_id':'first'})
    assert duplicate['data']['replayed_request']
    monkeypatch.setattr('agentos_runtime.gateway.Runtime.run',original)
    result=g.call('task_resume',{'task_id':task_id})
    assert result['data']['status']=='SUCCEEDED'
    assert count_tasks(home)==1


def test_errors_do_not_leak_exception_text(tmp_path,monkeypatch):
    _,g=setup(tmp_path)
    def fail(): raise OSError('/private/path SECRET_DO_NOT_LEAK')
    monkeypatch.setattr(g,'datasets_list',fail)
    result=g.call('datasets_list',{})
    assert result['error']['code']=='TOOL_IO_ERROR'
    assert 'SECRET' not in json.dumps(result)
    assert '/private/' not in json.dumps(result)


def cli(args,input_data=None):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    return subprocess.run([sys.executable,'-m','agentos_runtime',*args],input=input_data,
                          capture_output=True,text=True,encoding='utf-8',env=env,timeout=15)


def test_actual_cli_agent_round_trip_and_restart(tmp_path):
    home=tmp_path/'home'
    result=cli(['init-demo','--home',str(home),'--files','3'])
    assert result.returncode==0,result.stderr
    listed=cli(['tools','--home',str(home)])
    assert listed.returncode==0,listed.stderr
    assert len(json.loads(listed.stdout)['tools'])==8
    call={'tool':'task_submit','arguments':{'dataset_id':'demo','request_id':'same'}}
    response=cli(['tool','--home',str(home)],json.dumps(call))
    assert response.returncode==0,response.stderr
    first=json.loads(response.stdout)['data']
    response=cli(['tool','--home',str(home)],json.dumps(call))
    second=json.loads(response.stdout)['data']
    assert second['task_id']==first['task_id'] and second['replayed_request']
    artifact=first['artifacts'][0]
    read={'tool':'artifact_read','arguments':{'task_id':first['task_id'],'artifact_id':artifact['artifact_id']}}
    response=cli(['tool','--home',str(home)],json.dumps(read))
    assert response.returncode==0,response.stderr
    assert json.loads(response.stdout)['data']['content']
    assert count_tasks(home)==1


def test_cli_tools_utf8_when_stdio_is_legacy_codepage(tmp_path):
    home=tmp_path/'home'
    result=cli(['init-demo','--home',str(home),'--files','1'])
    assert result.returncode==0,result.stderr
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),
             PYTHONUTF8='0',PYTHONIOENCODING='cp1252')
    listed=subprocess.run([sys.executable,'-m','agentos_runtime','tools','--home',str(home)],
                          capture_output=True,env=env,timeout=15)
    assert listed.returncode==0,listed.stderr
    data=json.loads(listed.stdout.decode('utf-8'))
    assert len(data['tools'])==8
    assert '查询' in data['tools'][0]['description']


@pytest.mark.parametrize('payload', ['not-json', '{"tool":"datasets_list","arguments":{},"approved":true}', 'x'*65537],
                         ids=['not-json', 'extra-field', 'oversized'])
def test_cli_rejects_malformed_or_oversized_request(tmp_path,payload):
    home,_=setup(tmp_path)
    response=cli(['tool','--home',str(home)],payload)
    assert response.returncode==2
    assert count_tasks(home)==0
    assert len(response.stderr)<1000


def test_concurrent_duplicate_submissions_do_not_duplicate_work(tmp_path):
    home,g=setup(tmp_path)
    def work(_):
        client=AgentGateway(home)
        return client.call('task_submit',{'dataset_id':'demo','request_id':'one-request'})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(work,range(4)))
    assert all(r['ok'] for r in results), results
    assert len({r['data']['task_id'] for r in results})==1
    assert count_tasks(home)==1
    task_id=results[0]['data']['task_id']
    assert g.call('task_inspect',{'task_id':task_id})['data']['status']=='SUCCEEDED'
    with closing(sqlite3.connect(home/'tasks'/task_id/'run/journal.sqlite3')) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='operation_intent'").fetchone()[0]==4


def test_active_task_is_not_reported_as_needing_recovery(tmp_path,monkeypatch):
    home,g=setup(tmp_path)
    original=Runtime.run
    observations=[]
    def wrapper(self,*args,**kwargs):
        def observe(node,_):
            if node=='snapshot':
                with closing(sqlite3.connect(home/'registry.sqlite3')) as conn, conn:
                    task_id=conn.execute('SELECT task_id FROM tasks').fetchone()[0]
                observations.append(AgentGateway(home).call('task_inspect',{'task_id':task_id}))
        return original(self,*args,**kwargs,after_node=observe)
    monkeypatch.setattr('agentos_runtime.gateway.Runtime.run',wrapper)
    submit(g)
    assert observations[0]['data']['execution_active'] is True
    assert observations[0]['data']['needs_recovery'] is False


def test_artifacts_are_not_exposed_for_failed_task(tmp_path):
    home,g=setup(tmp_path)
    plan=default_plan().model_dump(); plan['limits']['max_rows']=1
    out=g.call('task_submit',{'dataset_id':'demo','request_id':'short','plan':plan})['data']
    assert out['status']=='FAILED'
    assert g.call('artifact_read',{'task_id':out['task_id'],'artifact_id':'0'*64})['error']['code']=='ARTIFACT_UNAVAILABLE'


def test_artifact_offset_and_strict_integer_validation(tmp_path):
    _,g=setup(tmp_path)
    task=submit(g); args={'task_id':task['task_id'],'artifact_id':task['artifacts'][0]['artifact_id']}
    assert g.call('artifact_read',{**args,'offset':16_777_216})['error']['code']=='OFFSET_RANGE'
    assert g.call('artifact_read',{**args,'max_chars':True})['error']['code']=='INVALID_ARGUMENT'


def test_owner_paths_cannot_be_symlinks(tmp_path):
    if os.name=='nt': pytest.skip('requires native Windows privilege test')
    home,g=setup(tmp_path)
    external=tmp_path/'external'; (home/'tasks').rename(external)
    (home/'tasks').symlink_to(external,target_is_directory=True)
    out=g.call('task_submit',{'dataset_id':'demo','request_id':'x'})
    assert out['error']['code']=='UNSUPPORTED_LINK'
    assert not list(external.iterdir())


def test_cli_resume_command(tmp_path):
    home,g=setup(tmp_path)
    result=submit(g)
    run=home/'tasks'/result['task_id']/'run'
    response=cli(['resume','--fixture',str(home/'fixtures/demo'),'--workspace',str(run)])
    assert response.returncode==0,response.stderr
    assert json.loads(response.stdout)['status']=='SUCCEEDED'


def test_cli_rejects_deeply_nested_request_without_traceback(tmp_path):
    home,_=setup(tmp_path)
    result=cli(['tool','--home',str(home)],'['*1200+'0'+']'*1200)
    assert result.returncode==2
    assert 'Traceback' not in result.stderr
    assert count_tasks(home)==0
