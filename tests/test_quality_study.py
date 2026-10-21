from copy import deepcopy
from backend.tools.indicators import digest
import pytest
from eval.quality_contracts import freeze, resolve_labels
from eval.quality_study import compare_study
from test_quality_metrics import fixture


def setup():
    f,l,p=fixture((1,2,4,5),(1,2,4,5));p['method']='single'
    conditions={'model':'test-fixture','tools_version':'1','catalog_hash':digest({c['id']:c['policies'] for c in f['dataset']['cases']}),'max_calls':10,'max_usd':1.0}
    q=deepcopy(p);q['method']='mas';q['predictions'][0]['grade']=5
    s={'version':'test','dataset_hash':f['dataset_hash'],'label_hash':resolve_labels(f,l)['label_hash'],
       'development_regions':[],'conditions':conditions,'arms':[{'conditions':deepcopy(conditions),'predictions':x} for x in (p,q)]}
    return f,l,s


def test_worse_mas_is_visible_and_missing_in_denominator():
    f,l,s=setup();r=compare_study(f,l,s);g=r['groups'][0];pair=g['paired'][0]
    assert pair['grade_accuracy_delta']==-.25 and pair['introduced_errors']==1
    assert pair['conclusion']=='improvement_not_established' and pair['confidence_interval'] is None
    s['arms'][1]['predictions']['predictions']=[]
    g=compare_study(f,l,s)['groups'][0]
    assert g['paired'][0]['grade_accuracy_delta']==-1 and g['arms'][1]['missing']==4
    assert g['transfer_scope']=='synthetic_robustness' and g['temporal_scope']=='not_evaluated'


def test_paired_source_families_are_not_pseudo_replication():
    f,l,s=setup();body=deepcopy(f['dataset']);body['cases'][1]['family_id']=body['cases'][0]['family_id']
    f=freeze(body);l['dataset_hash']=f['dataset_hash'];s['dataset_hash']=f['dataset_hash'];s['label_hash']=resolve_labels(f,l)['label_hash']
    for a in s['arms']:a['predictions']['dataset_hash']=f['dataset_hash']
    p=compare_study(f,l,s)['groups'][0]['paired'][0]
    assert p['family_count']==3 and p['grade_accuracy_delta']==pytest.approx(-1/6)


@pytest.mark.parametrize('change',['conditions','model','duplicate','labels','telemetry','time','catalog'])
def test_protocol_mismatch_and_time_leakage_rejected(change):
    f,l,s=setup();s=deepcopy(s)
    if change=='catalog':s['conditions']['catalog_hash']='wrong'
    if change=='conditions':s['arms'][0]['conditions']['max_calls']=9
    if change=='model':s['arms'][0]['predictions']['model']='other'
    if change=='duplicate':s['arms'][1]['predictions']['method']='single'
    if change=='labels':s['label_hash']='other'
    if change=='telemetry':s['arms'][0]['telemetry']=[{'run_id':'unknown','cost_usd':.1,'latency_seconds':1.0}]
    if change=='time':s['timing']={'0':{'input_available_at':'2026-01-02T00:00:00Z','predicted_at':'2026-01-01T00:00:00Z','outcome_available_at':'2026-02-01T00:00:00Z'}}
    with pytest.raises(ValueError):compare_study(f,l,s)


def test_known_development_regions_cannot_be_called_external():
    f,l,s=setup();body=deepcopy(f['dataset'])
    for c in body['cases']:c.update(source='observed',region='서울특별시 강남구',split='test')
    f=freeze(body);l['dataset_hash']=f['dataset_hash'];s['dataset_hash']=f['dataset_hash'];s['label_hash']=resolve_labels(f,l)['label_hash']
    for a in s['arms']:a['predictions']['dataset_hash']=f['dataset_hash']
    assert compare_study(f,l,s)['groups'][0]['transfer_scope']=='development_revalidation'
    assert compare_study(f,l,s,{'0'})['groups'][0]['case_count']==1


def test_run_cost_is_not_duplicated_across_case_repetitions():
    f,l,s=setup()
    for a in s['arms']:
        for p in a['predictions']['predictions']:p['run_id']=a['predictions']['method']
        a['telemetry']=[{'run_id':a['predictions']['method'],'cost_usd':.2,'latency_seconds':3.0}]
    c=compare_study(f,l,s)['costs'][0]
    assert c['known_cost_usd']==.2 and c['run_count']==1 and c['p95_seconds']==3


def test_valid_prospective_timestamp_and_target_period_leakage():
    f,l,s=setup();period=f['dataset']['cases'][0]['period'];year,month=map(int,period.split('-'))
    from datetime import datetime,timezone,timedelta
    start=datetime(year,month,1,tzinfo=timezone.utc)
    s['timing']={'0':{'input_available_at':(start-timedelta(days=2)).isoformat(),'predicted_at':(start-timedelta(days=1)).isoformat(),'outcome_available_at':(start+timedelta(days=35)).isoformat()}}
    assert compare_study(f,l,s)['groups'][0]['temporal_scope']=='not_evaluated'  # synthetic is never actual future
    s['timing']['0']['predicted_at']=start.isoformat()
    with pytest.raises(ValueError,match='forecast'):compare_study(f,l,s)


def test_same_run_across_methods_rejected():
    f,l,s=setup()
    for a in s['arms']:a['predictions']['predictions'][0]['run_id']='same'
    with pytest.raises(ValueError,match='reused'):compare_study(f,l,s)


def test_declared_development_history_required_for_external_scope():
    f,l,s=setup();body=deepcopy(f['dataset'])
    for c in body['cases']:c.update(source='observed',region='another-region',split='test')
    f=freeze(body);l['dataset_hash']=f['dataset_hash'];s['dataset_hash']=f['dataset_hash'];s['label_hash']=resolve_labels(f,l)['label_hash']
    for a in s['arms']:a['predictions']['dataset_hash']=f['dataset_hash']
    assert compare_study(f,l,s)['groups'][0]['transfer_scope']=='development_history_unconfirmed'
    s['development_regions']=['another-region']
    assert compare_study(f,l,s)['groups'][0]['transfer_scope']=='development_revalidation'
    s['development_regions']=['known-development-region']
    assert compare_study(f,l,s)['groups'][0]['transfer_scope']=='declared_external_test'
