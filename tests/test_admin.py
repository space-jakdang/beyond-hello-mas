import json
import pytest
from tests.test_graph import service, SIM, counts
from backend.app.contracts import Scenario
from backend.agents.person_stub import assess_stage, priority_score


def personal(kind='case', **changes):
    person={'person_id':'synthetic-person','age':24,'sgg':'11230','responses_confirmed':True,'consent':True,
        'responses':{'synthetic-contract-fixture':{'case':201}}, **changes}
    return Scenario(id='synthetic-person',type=kind,sim_time=SIM,payload={'person':person})


@pytest.fixture
def person_service(service,monkeypatch):
    async def remote(tool,args):
        return assess_stage(**args) if tool=='assess_stage' else priority_score(**args)
    monkeypatch.setattr(service.person,'remote',remote)
    return service


def test_high_stages_bypass_llm_and_approval_and_recover(person_service,monkeypatch):
    s=person_service
    def fail(*args):raise AssertionError('LLM must not precede handoff')
    monkeypatch.setattr(s.agents,'call',fail)
    for case in (201,202):
        run=s.start(personal(responses={'synthetic-contract-fixture':{'case':case}}))
        assert run.status=='completed' and counts(s,run.id)==(1,1)
        traces=s.store.traces(run.id)
        assert [t['agent'] for t in traces if t['kind']=='node_end']==['supervisor','classify','link']
        assert next(t for t in traces if t['kind']=='alert')['payload']['type']=='human_handoff'
        s.drive(run.id)
        assert counts(s,run.id)==(1,1)


def test_admin_followup_binding_and_ordinary_approval(person_service):
    s=person_service
    admin=s.start(personal('admin',responses={},responses_confirmed=False))
    assert admin.status=='completed'
    alert=next(t for t in s.store.traces(admin.id) if t['kind']=='alert')
    assert alert['payload']['type']=='screening_requested'
    case=s.start(personal(reply_to=admin.id,responses={'synthetic-contract-fixture':{'case':999}}))
    assert case.status=='awaiting_approval'
    with pytest.raises(ValueError,match='mismatch'):s.register(personal(reply_to=admin.id,person_id='different'))
    with pytest.raises(ValueError,match='completed admin'):s.register(personal(reply_to=case.id))


def test_unconfirmed_and_unavailable_route_to_people(person_service,monkeypatch):
    s=person_service
    def fail(*args):raise AssertionError('must not call model')
    monkeypatch.setattr(s.agents,'call',fail)
    without_consent=s.start(personal(consent=False))
    assert without_consent.status=='completed'
    assert not any(t['kind']=='tool_call' for t in s.store.traces(without_consent.id))
    run=s.start(personal(responses_confirmed=False))
    assert run.status=='completed'
    assert not any(t['kind']=='tool_call' for t in s.store.traces(run.id))
    async def unavailable(*args):raise ValueError('private detail')
    monkeypatch.setattr(s.person,'remote',unavailable)
    assert s.start(personal()).status=='completed'


def test_midlife_stage_three_and_four_use_human_connection(person_service,monkeypatch):
    s=person_service
    for stage in (3,4):
        async def remote(tool,args):
            return {**assess_stage(**args),'stage':stage,'human_handoff':False}
        monkeypatch.setattr(s.person,'remote',remote)
        run=s.start(personal(age=45))
        classification=next(t['payload'] for t in s.store.traces(run.id) if t['agent']=='classify' and t['kind']=='node_end')
        assert classification['response_category']=='human_connection'
        assert run.status=='completed'
