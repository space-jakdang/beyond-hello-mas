from types import SimpleNamespace
from backend.agents.regional import collaborate,issues
from tests.test_graph import service,scenario

OBS={'facts':[{'id':'a','stage':4}],'required_limitations':['not_individual'],'goal':'review regional evidence'}


def test_reviewer_feedback_changes_next_plan():
    calls=[];messages=[]
    class Agents:
        def call(self,run,ts,role,payload):
            calls.append((role,payload))
            if role=='regional_analyst':
                value={'summary':'supported','focus_ids':['a'],'limitations':[] if payload['round']==1 else ['not_individual']}
                if payload['round']==2:
                    assert payload['feedback'] and payload['previous_plan']['limitations']==[]
            else:value={'decision':'accept','concerns':[]}
            return SimpleNamespace(model_dump=lambda:value)
    result=collaborate(Agents(),'run','time',OBS,lambda *m:messages.append(m))
    assert result['status']=='reviewed' and len(result['rounds'])==2
    assert messages[2][1:3]==('regional_reviewer','regional_analyst')
    assert not issues(result['plan'],OBS)


def test_revision_cap_and_failure_do_not_publish_unchecked_plan():
    class Agents:
        def call(self,run,ts,role,payload):
            value={'summary':'unsupported','focus_ids':['invented'],'limitations':[]} if role=='regional_analyst' else {'decision':'revise','concerns':['not supported']}
            return SimpleNamespace(model_dump=lambda:value)
    result=collaborate(Agents(),'r','t',OBS,lambda *m:None)
    assert result['status']=='needs_human' and result['plan'] is None and len(result['rounds'])==2
    class Failed:
        def call(self,*a):raise ValueError('secret must not be logged')
    messages=[]
    result=collaborate(Failed(),'r','t',OBS,lambda *m:messages.append(m))
    assert result['reason']=='ValueError' and 'secret' not in str(messages)


def test_monthly_collaboration_keeps_rules_and_human_approval(service):
    run=service.start(scenario('monthly',ym='2025-09',collaboration=True))
    assert run.status=='awaiting_approval'
    proposal=service.approval(run.id)['proposal']
    assert len(proposal['assignments'])==376
    assert proposal['collaboration']['status']=='reviewed'
    assert proposal['priority_review_ids']==proposal['collaboration']['plan']['focus_ids']
    traces=service.store.traces(run.id,limit=1000)
    messages=[t for t in traces if t['kind']=='agent_message']
    assert [(t['payload']['sender'],t['payload']['recipient']) for t in messages]==[
        ('supervisor','regional_analyst'),('regional_analyst','regional_reviewer'),('regional_reviewer','supervisor'),('supervisor','match')]
    assert len([t for t in traces if t['kind']=='llm_call'])==2
    restored=service.drive(run.id)
    assert restored.status=='awaiting_approval'
    assert len([t for t in service.store.traces(run.id,limit=1000) if t['kind']=='agent_message'])==4
