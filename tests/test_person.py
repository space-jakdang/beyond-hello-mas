from uuid import uuid4
import pytest
from pydantic import ValidationError
from backend.agents.person import PersonAdapter, PersonInput, Priority, age_group
from backend.agents.person_stub import assess_stage
from backend.app.config import Settings
from backend.app.contracts import Scenario
from backend.events import EventStore
from backend.graph import GraphService

SIM='2025-07-01T09:00:00+09:00'


@pytest.fixture
def adapter(tmp_path,monkeypatch):
    import backend.app.config as config
    monkeypatch.setattr(config,'ROOT',tmp_path)
    settings=Settings(_env_file=None,llm_mode='fake',person_mcp_mode='stub')
    store=EventStore(settings.runtime_dir/'events.sqlite3')
    graph=GraphService(store,settings)
    run=graph.register(Scenario(id='person-contract',type='case',sim_time=SIM,payload={}))
    return PersonAdapter(store,settings),run.id


def test_age_boundaries_and_strict_inputs():
    assert [age_group(n) for n in (19,34,35,49,50,64,65,120)]==['youth','youth','midlife','midlife','prime','prime','elderly','elderly']
    for age in (18,121,True):
        with pytest.raises(ValueError):age_group(age)
    for bad in [{'age':34,'age_group':'midlife'}, {'age':35,'age_group':'midlife','responses':{'x':{'a':True}}},
                {'age':50,'age_group':'prime','admin_flags':{'unrecognized':True}}]:
        with pytest.raises(ValidationError):PersonInput.model_validate(bad)


def test_actual_stdio_stub_contract_and_raw_answers_not_traced(adapter):
    client,run=adapter
    request={'age':24,'age_group':'youth','responses':{'synthetic-contract-fixture':{'case':201}},'admin_flags':{}}
    result=client.assess(run,SIM,request)
    assert result['status']=='assessed' and result['synthetic']
    assert result['result']['stage']==4 and result['result']['human_handoff']
    assert result['result']['lsis6'] is None
    score=client.priority(run,SIM,'midlife',{'became_alone':True})
    assert score['result']['grade'] is None and score['result']['score']==0
    assert all('responses' not in t['payload'] for t in client.store.traces(run))
    calls=[t for t in client.store.traces(run) if t['kind']=='tool_call']
    assert all('input_hash' in t['payload'] for t in calls)


def test_handoff_is_enforced_and_invalid_result_fails_closed(adapter,monkeypatch):
    client,run=adapter
    async def remote(tool,args):
        result=assess_stage('youth',24,{'synthetic-contract-fixture':{'case':201}},{});result['human_handoff']=False
        return result
    monkeypatch.setattr(client,'remote',remote)
    result=client.assess(run,SIM,{'age':24,'age_group':'youth'})
    assert result['result']['human_handoff']
    async def bad(tool,args):raise ValueError('PRIVATE_SERVER_EXCEPTION')
    monkeypatch.setattr(client,'remote',bad)
    output=client.assess(run,SIM,{'age':24,'age_group':'youth'})
    assert output['status']=='unavailable' and output['human_review_required']
    assert 'PRIVATE_SERVER_EXCEPTION' not in str(client.store.traces(run))


def test_pending_local_stub_refusal_and_live_no_fallback(adapter):
    client,run=adapter
    pending=client.assess(run,SIM,{'age':70,'age_group':'elderly'})
    assert pending['status']=='assessment_pending'
    client.settings.data_mode='local'
    assert client.assess(run,SIM,{'age':70,'age_group':'elderly'})['status']=='unavailable'
    client.settings.person_mcp_mode='live';client.settings.mcp_python=None
    assert client.assess(run,SIM,{'age':70,'age_group':'elderly'})['status']=='unavailable'


def test_priority_rejects_inconsistent_contributions_and_unvalidated_grades(adapter,monkeypatch):
    raw={'score':2,'grade':None,'band':None,'contributions':[{'item':'synthetic','points':1}],
         'scorecard_version':'test','status':'complete','sources':['fixture'],'warnings':[]}
    with pytest.raises(ValidationError):Priority.model_validate(raw)
    client,run=adapter
    async def remote(tool,args):return {**raw,'score':1,'grade':3}
    monkeypatch.setattr(client,'remote',remote)
    assert client.priority(run,SIM,'midlife',{})['status']=='unavailable'
    assert client.priority(run,SIM,'elderly',{})['status']=='unavailable'


def test_negative_contributions_are_preserved():
    result=Priority(score=2,grade=None,band=None,contributions=[{'item':'synthetic-A','points':-2},{'item':'synthetic-B','points':4}],
                    scorecard_version='fixture',status='complete',sources=['synthetic'],warnings=[])
    assert [r.points for r in result.contributions]==[-2,4]


def test_remote_failure_status_and_live_stub_are_rejected(adapter,monkeypatch):
    from backend.agents.person_stub import priority_score
    client,run=adapter
    async def failed(tool,args):
        return {**priority_score('youth',{}),'status':'failed'}
    monkeypatch.setattr(client,'remote',failed)
    assert client.priority(run,SIM,'youth',{})['status']=='unavailable'
    async def synthetic(tool,args):return assess_stage('youth',24,{'synthetic-contract-fixture':{'case':202}}, {})
    monkeypatch.setattr(client,'remote',synthetic)
    client.settings.person_mcp_mode='live'
    assert client.assess(run,SIM,{'age':24,'age_group':'youth'})['status']=='unavailable'


def test_synthetic_cases_are_explicit_protocol_fixtures():
    for case,stage,track,crisis in [(202,5,'isolation',True),(203,2,'care_health',False),(999,2,'isolation',False)]:
        result=assess_stage('youth',24,{'synthetic-contract-fixture':{'case':case}}, {})
        assert (result['stage'],result['track'],result['crisis'])==(stage,track,crisis)
        assert result['rule_version']=='stub-v02'
