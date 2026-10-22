from copy import deepcopy
import pytest
from tests.test_graph import service,scenario
from eval.alternative_quality import quality,AXES


def proposals(service):
    run=service.register(scenario());scope={'sgg':'11230','ym':'2025-09','as_of':'2026-10-23','target_groups':['M/youth']}
    return service.policy_designer.propose(run.id,run.id,scope,[{'dong_cd':'11230680','dong_nm':'검증동'}],[])


def test_completion_never_implies_quality_and_reference_version_is_strict(service):
    data=proposals(service);report=quality(data)
    assert report['exactly_three']==1 and report['template_count']==3 and report['grounding_eligible']==0
    assert all(v['value'] is None for row in report['rows'] for v in row['rubric'].values())
    ratings={'input_hash':report['input_hash'],'reviewers':[{'id':x,'expertise':'복지','development_participant':False} for x in ['one','two']],
             'ratings':[{'alternative_id':data[0]['alternatives'][0]['id'],'reviewer':x,'scores':dict.fromkeys(AXES,score),'reason':'독립 검토'} for x,score in [('one',2),('two',5)]]}
    rated=quality(data,ratings);assert rated['rows'][0]['rubric']['feasibility']['state']=='disagreement'
    ratings['ratings'][1]['scores']=dict.fromkeys(AXES,3)
    assert quality(data,ratings)['rows'][0]['rubric']['feasibility']['value']==2.5
    changed=deepcopy(data);changed[0]['review_revision']=1
    with pytest.raises(ValueError,match='another proposal'):quality(changed,ratings)
    invalid=deepcopy(ratings);invalid['ratings'][0]['scores']['grounding']=True
    with pytest.raises(ValueError):quality(data,invalid)
    ratings['reviewers'][1]['development_participant']=True
    assert quality(data,ratings)['rows'][0]['rubric']['feasibility']['value'] is None


def test_template_ragas_excluded_and_replay_is_free(service,monkeypatch):
    pytest.importorskip('ragas')
    import asyncio
    import eval.ragas_judge as judges
    from eval.alternative_grounding import evaluate
    data=proposals(service)
    monkeypatch.setattr(judges,'BudgetedJudge',lambda *args:pytest.fail('templates must not call judge'))
    result=asyncio.run(evaluate(service.store,service.settings,data[0]['owner_id']))
    assert result['judge_run_id'] is None and len(result['rows'])==3 and all(r['value'] is None for r in result['rows'])
    assert asyncio.run(evaluate(service.store,service.settings,data[0]['owner_id']))==result


@pytest.mark.parametrize('identifier,mode',[('E1','fixture'),('E99','template_fallback')])
def test_short_model_references_restore_exact_source_ids(service,monkeypatch,identifier,mode):
    from types import SimpleNamespace
    from uuid import uuid4
    from tests.test_workflow_agents import run_task
    from backend.policy.alternatives import templates
    run=run_task(service);proposal=service.approval(run.id)['proposal']
    fact=next(r for r in proposal['assessment']['segments'] if r['value'] is not None and r['stage'] is not None)
    def call(run,sim,role,view):
        assert view['facts'][0]['evidence_id']=='E1'
        output=templates(view)
        for item in output['alternatives']:item['problem_evidence_ids']=[identifier]
        return SimpleNamespace(model_dump=lambda:output)
    monkeypatch.setattr(service.agents,'call',call);monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:{'status':'unavailable'})
    body=service.policy_designer.propose(str(uuid4()),run.id,{**proposal['task'],'target_groups':[proposal['task']['sex']+'/'+proposal['task']['age_group']]},[{'dong_cd':fact['dong_cd'],'dong_nm':fact['dong_nm']}],[proposal])[0]
    assert all(a['problem_evidence_ids']==([fact['evidence_id']] if mode=='fixture' else []) and a['generation_mode']==mode for a in body['alternatives'])


def test_quality_api_keeps_ratings_bound_to_current_revision(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.alternative_quality import router
    data=proposals(service);owner=data[0]['owner_id'];app=FastAPI();app.include_router(router(service.store));client=TestClient(app)
    report=client.get('/policy-proposals/'+owner+'/quality').json()
    assert client.get('/policy-proposals').json()[0]['owner_id']==owner
    payload={'input_hash':report['input_hash'],'reviewers':[],'ratings':[]}
    assert client.post('/policy-proposals/'+owner+'/quality/ratings',json=payload).status_code==200
    assert client.post('/policy-proposals/'+owner+'/quality/ratings',json={**payload,'input_hash':'wrong'}).status_code==422
    person={'id':'one','expertise':'복지','development_participant':False}
    rating={'alternative_id':data[0]['alternatives'][0]['id'],'reviewer':'one','scores':dict.fromkeys(AXES,3),'reason':'독립 검토'}
    first={**payload,'reviewers':[person],'ratings':[rating]}
    assert client.post('/policy-proposals/'+owner+'/quality/ratings',json=first).status_code==200
    assert client.post('/policy-proposals/'+owner+'/quality/ratings',json={**first,'ratings':[{**rating,'reason':'different'}]}).status_code==409
    second={**payload,'reviewers':[{**person,'id':'two'}],'ratings':[{**rating,'reviewer':'two'}]}
    response=client.post('/policy-proposals/'+owner+'/quality/ratings',json=second)
    assert response.status_code==200 and response.json()['rows'][0]['rubric']['feasibility']['independent_count']==2
