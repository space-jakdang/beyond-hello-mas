from copy import deepcopy
import json
import pytest
from backend.tools.regional_task import assess
from eval.run_regional_quality import capture,execute,study_for,validate_report
from eval.rate_regional_quality import packet,aggregate
from eval.quality_study import compare_study
from tests.test_graph import service
from tests.test_regional_task import task


def inputs(service):
    row=next(r for r in assess(service.settings,task())['segments'] if r['stage'] is not None)
    return capture(service.settings,[task(dong_cd=row['dong_cd'],goal='월별 추이를 확인하세요.').model_dump(mode='json'),
                                     task(dong_cd=row['dong_cd'],sex='F',age_group='prime').model_dump(mode='json')])


@pytest.fixture
def recorded(service):
    frozen=inputs(service);report=execute(frozen,service.settings,service.store)
    return frozen,report


def test_real_graph_arms_use_frozen_sources_separate_runs_and_shared_budgets(service,monkeypatch):
    frozen=inputs(service)
    monkeypatch.setattr('backend.graph.load_catalog',lambda *a:pytest.fail('must use frozen catalog'))
    monkeypatch.setattr('backend.tools.regional_task.load_segments',lambda *a:pytest.fail('must use frozen observations'))
    report=execute(frozen,service.settings,service.store)
    assert validate_report(frozen,report)
    assert report['evaluation_scope']=='regional_interpretation_and_conditional_catalog_candidates'
    assert report['independent_quality']=='not_evaluated'
    assert len({r['run_id'] for r in report['records']})==6
    assert all(r['run_status']=='awaiting_approval' for r in report['records'])
    assert all(r['calls']<=report['conditions']['max_calls'] for r in report['records'])
    assert all(r['calls']==0 for r in report['records'] if r['method']=='rules')
    single=[r for r in report['records'] if r['method']=='single']
    for record in single:
        with service.store.connection() as db:
            roles={r[0] for r in db.execute('SELECT role FROM llm_calls WHERE run_id=?',(record['run_id'],))}
        assert roles=={'workflow_single'}
        assert record['proposal']['workflow']['statistics']['review_mode']=='single_self_review'
    assert [[p['grade'] for p in a['predictions']['predictions']] for a in report['arms']].count([p['grade'] for p in report['arms'][0]['predictions']['predictions']])==3
    labels={'dataset_hash':frozen['dataset_hash'],'reviewers':[],'judgments':[]}
    compared=compare_study(frozen,labels,study_for(frozen,labels,report))
    assert all(p['grade_accuracy_delta'] is None for g in compared['groups'] for p in g['paired'])
    assert all(c['known_cost_usd']==0 and c['unknown_cost_runs']==0 for c in compared['costs'])
    for record in report['records']:
        with service.store.connection() as db:assert db.execute('SELECT COUNT(*) FROM linkages WHERE run_id=?',(record['run_id'],)).fetchone()[0]==0


def test_adapter_rejects_changed_input_catalog_and_forged_source_links(service,recorded):
    frozen,report=recorded
    for change in ('stage','catalog','link','prediction'):
        bad=deepcopy(report)
        if change=='stage':bad['records'][0]['proposal']['assessment']['segments'][0]['stage']=5
        if change=='catalog':bad['records'][0]['proposal']['assessment']['catalog_snapshot']=[]
        if change=='link':bad['arms'][1]['predictions']['predictions'][0]['run_id']=bad['records'][0]['run_id']
        if change=='prediction':bad['arms'][0]['predictions']['predictions'][0]['grade']=5
        with pytest.raises(ValueError):validate_report(frozen,bad)
    bad=deepcopy(frozen);bad['dataset']['cases'][0]['facts']['assessment']['segments'][0]['stage']=5
    from eval.quality_contracts import freeze
    with pytest.raises(ValueError,match='source calculation'):execute(freeze(bad['dataset']),service.settings,service.store)


def test_failed_single_calls_remain_failed_matching_and_unknown_cost(service,monkeypatch):
    from backend.agents import llm
    original=llm.fake
    def fail(role,payload):
        if role=='workflow_single':raise RuntimeError('synthetic provider failure')
        return original(role,payload)
    monkeypatch.setattr(llm,'fake',fail)
    frozen=inputs(service);report=execute(frozen,service.settings,service.store)
    single=report['arms'][1]['predictions']['predictions']
    assert all(p['resources']['status']=='failed' and not p['resources']['recommended_ids'] for p in single)
    assert all(r['calls']==1 for r in report['records'] if r['method']=='single')
    assert all(r['unknown_cost_calls']==1 and r['telemetry']['cost_usd'] is None for r in report['records'] if r['method']=='single')
    assert validate_report(frozen,report)


def ratings_for(key):
    reviewers=[{'id':identifier,'expertise':'synthetic fixture reviewer','development_participant':False} for identifier in ('r1','r2','adjudicator')]
    return {'reviewers':reviewers,'ratings':[{'blind_id':identifier,'reviewer':reviewer,'executable':True,'major_errors':[],
        'reason':'SYNTHETIC PRIVATE RATING','supported_claims':1,'reviewed_claims':1,'omitted_constraints':False,'appropriate_hold':True,
        'excessive_hold':False,'edits':2,'task_seconds':30.0} for identifier in key['mapping'] for reviewer in ('r1','r2')],'adjudications':[]}


def test_blind_output_ratings_keep_missing_development_and_disagreement(recorded):
    frozen,report=recorded;public,key=packet(frozen,report)
    assert '"method":' not in json.dumps(public) and '"run_id":' not in json.dumps(public)
    empty=aggregate(frozen,report,key,{'reviewers':[],'ratings':[]})
    assert all(m['success_rate'] is None and m['missing']==2 for m in empty['methods'])
    data=ratings_for(key);summary=aggregate(frozen,report,key,data)
    assert all(m['resolved']==2 and m['family_success_rate']==1 and m['mean_edits']==2 for m in summary['methods'])
    assert not summary['evaluation_complete'] and summary['adoption_decision']=='not_evaluated'
    assert 'SYNTHETIC PRIVATE RATING' not in json.dumps(summary) and 'reviewers' not in summary
    data['ratings'][0]['omitted_constraints']=True
    summary=aggregate(frozen,report,key,data)
    assert sum(m['disagreement'] for m in summary['methods'])==1
    identifier=data['ratings'][0]['blind_id']
    data['adjudications']=[{'blind_id':identifier,'reviewer':'adjudicator','executable':True,'major_errors':[],
        'reason':'fixture adjudication','omitted_constraints':False,'appropriate_hold':True,'excessive_hold':False}]
    assert sum(m['resolved'] for m in aggregate(frozen,report,key,data)['methods'])==6
    data['reviewers'][0]['development_participant']=True
    assert all(m['not_independent']==2 and m['success_rate'] is None for m in aggregate(frozen,report,key,data)['methods'])
    changed=deepcopy(report);changed['mode']='live'
    with pytest.raises(ValueError,match='changed'):aggregate(frozen,changed,key,data)


def test_duplicate_rating_or_run_link_cannot_inflate_denominator(recorded):
    frozen,report=recorded;_,key=packet(frozen,report);data=ratings_for(key)
    data['ratings'].append(data['ratings'][0])
    with pytest.raises(ValueError,match='duplicate rating'):aggregate(frozen,report,key,data)
    bad=deepcopy(key);bad['mapping'][next(iter(bad['mapping']))]['run_id']='another-run'
    with pytest.raises(ValueError,match='blinding map'):aggregate(frozen,report,bad,ratings_for(key))


def test_shared_source_runs_are_charged_once_and_scales_are_not_pooled(service):
    from eval.quality_contracts import freeze
    from eval.quality_metrics import classification
    body=capture(service.settings,[task().model_dump(mode='json')])['dataset'];body['cases']=body['cases'][:2]
    frozen=freeze(body);report=execute(frozen,service.settings,service.store)
    assert len(report['records'])==3 and all(len(r['case_ids'])==2 for r in report['records'])
    assert all(len(arm['telemetry'])==1 for arm in report['arms'])
    assert all(r['proposal']['workflow']['statistics']['status']=='reviewed' for r in report['records'])
    assert validate_report(frozen,report)
    labels={'dataset_hash':frozen['dataset_hash'],'reviewers':[],'judgments':[]}
    group=classification(frozen,labels,report['arms'][0]['predictions'])['groups'][0]
    assert group['stage_scale'] and group['priority_criterion_status']=='not_established'
    assert group['priority_recall'] is None and group['flag_rate'] is None


def test_quality_api_filters_output_ratings_without_exposing_private_raters(tmp_path,recorded):
    from uuid import uuid4
    from fastapi import HTTPException
    from backend.app.quality_reports import quality_body
    frozen,report=recorded;public,key=packet(frozen,report);identifier=uuid4();folder=tmp_path/str(identifier);folder.mkdir()
    labels={'dataset_hash':frozen['dataset_hash'],'reviewers':[],'judgments':[]}
    for name,body in [('inputs',frozen),('labels',labels),('workflow-runs',report),('study',study_for(frozen,labels,report))]:
        (folder/(name+'.json')).write_text(json.dumps(body))
    detail=quality_body(folder,'sample',identifier)
    assert all(m['missing']==2 and m['success_rate'] is None for m in detail['workflow_quality']['methods'])
    for name,body in [('workflow-private-key',key),('workflow-ratings',ratings_for(key))]:(folder/(name+'.json')).write_text(json.dumps(body))
    detail=quality_body(folder,'sample',identifier)
    assert detail['status']=='partial' and all(m['resolved']==2 for m in detail['workflow_quality']['methods'])
    assert 'SYNTHETIC PRIVATE RATING' not in json.dumps(detail) and 'adjudicator' not in json.dumps(detail)
    assert all(m['case_count']==0 for m in quality_body(folder,'sample',identifier,region='absent')['workflow_quality']['methods'])
    (folder/'workflow-private-key.json').rename(folder/'private-saved.json')
    (folder/'workflow-private-key.json').symlink_to(folder/'private-saved.json')
    with pytest.raises(HTTPException) as error:quality_body(folder,'sample',identifier)
    assert error.value.status_code==409


def test_isolated_run_evidence_uses_recorded_proposal_and_generic_recovery_cannot_change_method(service,recorded):
    from uuid import uuid4
    from backend.app.quality_jobs import QualityJobs,case_evidence
    from eval.run_regional_quality import QualityGraph
    frozen,report=recorded;identifier=uuid4();folder=service.settings.runtime_root/'quality/sample'/str(identifier);folder.mkdir(parents=True)
    labels={'dataset_hash':frozen['dataset_hash'],'reviewers':[],'judgments':[]}
    for name,body in [('inputs',frozen),('labels',labels),('workflow-runs',report),('predictions',report['arms'][-1]['predictions'])]:
        (folder/(name+'.json')).write_text(json.dumps(body))
    jobs=QualityJobs(service.store,service.settings)
    evidence=case_evidence(jobs,identifier,frozen['dataset']['cases'][0]['id'],'sample')
    assert evidence['run_id'] is None and evidence['source_run_id'] and evidence['rows']
    assert evidence['rows'][0]['decision_evidence']['matching_mode']=='deterministic-regional-1'
    single=next(r for r in report['records'] if r['method']=='single');run_id=single['run_id']
    before=service.store.traces(run_id,limit=1000)
    with pytest.raises(ValueError,match='recorded method'):service.drive(run_id)
    wrong=QualityGraph(service.store,service.settings,single['proposal']['assessment'],'mas')
    with pytest.raises(ValueError,match='recorded method'):wrong.drive(run_id)
    correct=QualityGraph(service.store,service.settings,single['proposal']['assessment'],'single')
    assert correct.drive(run_id).status=='awaiting_approval'
    assert service.store.traces(run_id,limit=1000)==before
    from tests.test_graph import scenario
    with service.store.connection() as db:count=db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
    with pytest.raises(ValueError,match='recorded method'):
        service.register(scenario(evaluation_protocol='regional-quality-1',evaluation_method='single',evaluation_input_hash='untrusted'))
    with service.store.connection() as db:assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==count


@pytest.mark.parametrize('invalid',['evidence','duplicate_tool','budget'])
def test_single_agent_invalid_selection_repeat_lookup_and_budget_hold(service,monkeypatch,invalid):
    from backend.agents import llm
    original=llm.fake
    def response(role,payload):
        result=original(role,payload)
        if role=='workflow_single':
            if invalid=='evidence':result['plan']['priority_evidence_ids']=['unobserved']
            elif invalid=='duplicate_tool':result.update(action='lookup',tool='source_check')
        return result
    monkeypatch.setattr(llm,'fake',response)
    if invalid=='budget':service.settings.llm_max_calls=1
    frozen=inputs(service);report=execute(frozen,service.settings,service.store)
    first=next(r for r in report['records'] if r['method']=='single')
    assert first['proposal']['workflow']['analysis'] is None
    assert first['proposal']['workflow']['statistics']['status']=='needs_human'
    assert all(not row['recommendations'] for row in first['proposal']['assignments'])
