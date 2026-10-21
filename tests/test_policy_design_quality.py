from copy import deepcopy
import pytest
from eval.policy_design_quality import quality,AXES
from backend.policy.design_contracts import validate_draft
from tests.test_policy_design_contracts import fixture as draft_fixture
from test_quality_metrics import fixture


def inputs():
    frozen,_,_=fixture((3,),(3,));draft,gap,sources=draft_fixture()
    doc=validate_draft(draft,['obs'],gap,sources);doc['status']='draft'
    return frozen,{'dataset_hash':frozen['dataset_hash'],'cases':[{'case_id':'0','document':doc,'run_id':None}]}


def test_missing_independent_review_is_not_perfect_policy_quality():
    frozen,body=inputs();result=quality(frozen,body);row=result['rows'][0]
    assert row['source_validation'] is True and row['field_effectiveness'] is None
    assert all(m['mean'] is None and m['state']=='not_evaluated' for m in row['rubric'].values())
    ratings={'input_hash':result['input_hash'],'reviewers':[{'id':'a','expertise':'policy','development_participant':True}],
        'ratings':[{'case_id':'0','version':body['cases'][0]['document']['version'],'reviewer':'a','reviewed_at':'2026-10-22','scores':dict.fromkeys(AXES,5),'reason':'개발자 확인'}]}
    assert quality(frozen,body,ratings)['rows'][0]['independent_reviews']==0


def test_disagreement_version_tampering_and_duplicate_reviews():
    frozen,body=inputs();baseline=quality(frozen,body)
    ratings={'input_hash':baseline['input_hash'],'reviewers':[{'id':id,'expertise':'policy','development_participant':False} for id in ('a','b')],
        'ratings':[{'case_id':'0','version':body['cases'][0]['document']['version'],'reviewer':id,'reviewed_at':'2026-10-22','scores':dict.fromkeys(AXES,score),'reason':'독립 평정'} for id,score in [('a',1),('b',5)]]}
    row=quality(frozen,body,ratings)['rows'][0]
    assert row['rubric']['feasibility']['state']=='disagreement' and row['rubric']['feasibility']['mean'] is None
    ratings['ratings'][1]['scores']=dict.fromkeys(AXES,2)
    assert quality(frozen,body,ratings)['rows'][0]['rubric']['clarity']['mean']==1.5
    bad=deepcopy(body);bad['cases'][0]['document']['draft']['title']='changed'
    with pytest.raises(ValueError):quality(frozen,bad)
    ratings['ratings'].append(ratings['ratings'][0])
    with pytest.raises(ValueError):quality(frozen,body,ratings)


def test_dashboard_job_freezes_draft_inputs_and_keeps_unrated_scores_missing(tmp_path,monkeypatch):
    import json
    from uuid import uuid4
    from backend.app import config
    from backend.app.quality_jobs import QualityJobs
    from backend.events import EventStore
    frozen,body=inputs();monkeypatch.setattr(config,'ROOT',tmp_path)
    settings=config.Settings(_env_file=None,llm_mode='fake',data_mode='sample');folder=tmp_path/'runtime/quality/sample'/str(uuid4());folder.mkdir(parents=True)
    labels={'dataset_hash':frozen['dataset_hash'],'reviewers':[],'judgments':[]}
    for name,value in [('inputs',frozen),('labels',labels),('policy-drafts',body)]: (folder/f'{name}.json').write_text(json.dumps(value))
    jobs=QualityJobs(EventStore(settings.runtime_dir/'events.sqlite3'),settings)
    job=jobs.register(folder.name,'sample','deterministic');(folder/'policy-drafts.json').write_text('{}')
    jobs.execute(job['id']);saved=jobs.get(job['id'])
    assert saved['status']=='completed' and saved['result']['policy_design']['rows'][0]['independent_reviews']==0
    assert saved['result']['status']=='not_evaluated'
