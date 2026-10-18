import json
from pathlib import Path
import pytest
from eval.metrics import fraction, percentile, summarize
from eval.run_suite import inputs, read_ratings


def result(id,truth,prediction,**changes):
    return {'scenario_id':id,'expected_crisis':truth,'predicted_crisis':prediction,'path_correct':False,'causes_correct':False,'route_correct':False,'relevant_recommendations':0,'recommendation_count':0,'evidence_checked':0,'evidence_mismatches':0,'receipt_ms':None,'expects_alert':True,'known_cost_usd':0,'unknown_cost_calls':0,'status':'failed',**changes}


def test_hand_calculated_confusion_precision_latency_and_unknown_cost():
    rows=[result('S3-1',True,True,receipt_ms=10),result('S3-2',True,False,receipt_ms=20),result('S3-3',False,True),result('S3-4',False,False),result('S2-1',False,False,relevant_recommendations=2,recommendation_count=2,unknown_cost_calls=1,known_cost_usd=.01)]
    metrics=summarize(rows)
    assert metrics['crisis_confusion']=={'TP':1,'FN':1,'FP':1,'TN':1}
    assert metrics['crisis_recall']['value']==.5
    assert metrics['crisis_false_positive_rate']['value']==.5
    assert metrics['precision_at_3']['value']==2/3
    assert metrics['recommendation_shortfall']==1
    assert metrics['latency']['p50_ms']==10 and metrics['latency']['p95_ms']==20
    assert metrics['latency']['missing']==3
    assert metrics['cost']['total_usd'] is None and metrics['cost']['known_usd']==.01
    assert metrics['human_suitability']['mean'] is None
    assert fraction(0,0)['value'] is None and percentile([],.95) is None


def test_fixed_inputs_no_label_leak_and_human_ratings_validation(tmp_path):
    scenarios,labels=inputs()
    assert len(scenarios)==40
    assert [sum(s.type==kind for s in scenarios) for kind in ('monthly','case','crisis','question')]==[6,16,8,10]
    assert all('expected' not in s.model_dump_json() for s in scenarios)
    path=tmp_path/'ratings.json'
    for row in ({'scenario_id':'S2-1-1','score':True,'reviewer':'test'}, {'scenario_id':'S1-07','score':5,'reviewer':'test'}, {'scenario_id':'S2-1-1','score':5,'reviewer':''}):
        path.write_text(json.dumps([row]))
        with pytest.raises(ValueError):read_ratings(path,labels)
    row={'scenario_id':'S2-1-1','score':4,'reviewer':'test'}
    path.write_text(json.dumps([row,row]))
    with pytest.raises(ValueError):read_ratings(path,labels)


def test_comparison_rejects_changed_provenance():
    from copy import deepcopy
    from eval.compare import compare
    report={'id':'one','metadata':{'git_commit':'a'},'data_mode':'sample','llm_mode':'fake','model':'fake-v1','results':[],'stage_reproducibility':{'hashes':['a']},'metrics':{'latency':{},'cost':{}}}
    other=deepcopy(report);other['id']='two'
    assert compare(report,other)['deterministic_outputs_identical']
    other['metadata']['git_commit']='b'
    with pytest.raises(ValueError):compare(report,other)


def test_reports_are_mode_scoped_and_uuid_validated(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app import config
    from backend.app.report_routes import report_router
    from uuid import uuid4
    monkeypatch.setattr(config,'ROOT',tmp_path)
    ids=[str(uuid4()),str(uuid4())]
    for id,mode in zip(ids,('fake','live')):
        path=tmp_path/'eval/reports/20261018'/id
        path.mkdir(parents=True)
        (path/'summary.json').write_text(json.dumps({'id':id,'data_mode':'sample','llm_mode':mode,'status':'partial','evaluated_scenarios':40,'created_at':'2026-10-18'}))
    app=FastAPI();app.include_router(report_router(config.Settings(data_mode='sample',llm_mode='fake')))
    with TestClient(app) as client:
        assert [r['id'] for r in client.get('/reports').json()]==ids[:1]
        assert client.get('/reports/'+ids[0]).json()['evaluated_scenarios']==40
        assert client.get('/reports/'+ids[1]).status_code==404
        assert client.get('/reports/not-uuid').status_code==422
