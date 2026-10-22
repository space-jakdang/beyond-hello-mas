from copy import deepcopy
from backend.tools.policy_insights import insights,persistence
from backend.tools.regional_task import assess
from tests.test_regional_task import task
from tests.test_graph import service


def test_single_dong_compares_only_same_period_definition_and_excludes_self(service):
    full=assess(service.settings,task())
    row=full['segments'][0]
    single=assess(service.settings,task(dong_cd=row['dong_cd']))
    result=insights(single)['items'][0]
    assert result['comparison']['peer_count']==len(full['segments'])-1
    contaminated=deepcopy(single)
    for r in contaminated['source_observations']:
        if r['dong_cd']!=row['dong_cd']:r['source_period']='incompatible'
    assert insights(contaminated)['items'][0]['comparison']['risk_direction_difference'] is None
    assert not any(r['ym'] and r['ym']>single['task']['ym'] for r in single['source_observations'])


def test_persistence_requires_three_consecutive_comparable_observations():
    observation={'series':[{'cohort_id':'a','points':[{'ym':'2025-01','change':None},{'ym':'2025-02','change':1},{'ym':'2025-03','change':2}]}]}
    assert persistence(observation)[0]['direction']=='increasing'
    observation['series'][0]['points'][1]['change']=None
    assert persistence(observation)[0]['direction']=='unavailable'


def test_new_statistics_can_request_three_distinct_tools(service,monkeypatch):
    from backend.agents.workflow import statistical_review,analyze
    from tests.test_graph import scenario
    from time import time
    import backend.agents.llm as module
    original=module.fake
    def fake(role,payload):
        if role=='workflow_statistics':
            step=payload['step']
            return {'action':'lookup' if step<3 else 'finish','tool':['source_check','sensitivity','policy_insights','trend'][step],
                    'reason':'도구별 정책 근거 확인','blocked_evidence_ids':[]}
        return original(role,payload)
    monkeypatch.setattr(module,'fake',fake);service.settings.llm_max_calls=8
    run=service.register(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    a=assess(service.settings,task());a['metadata']['statistics_version']='2'
    plan=analyze(service.agents,run.id,'2025-09-01',a)
    result=statistical_review(service.agents,service.settings,run.id,'2025-09-01',a,plan,lambda *args:None,time()+120)
    assert result['status']=='reviewed' and len(result['observations'])==3
