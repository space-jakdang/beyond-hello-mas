from copy import deepcopy
import pytest
from eval.quality_contracts import freeze
from eval.quality_matching import matching
from eval.quality_metrics import validate_predictions
from test_quality_metrics import fixture
from test_quality_contracts import judgment


def resource_fixture():
    f,l,p=fixture((3,),(3,));body=deepcopy(f['dataset'])
    body['cases'][0]['policies']={pid:{'title':pid,'url':'https://example.org/'+pid} for pid in ('good','conditional','bad','missing')}
    body['cases'][0]['policies']['bad']['constraint_checks']={'jurisdiction':'fail'}
    f=freeze(body);l['dataset_hash']=f['dataset_hash'];p['dataset_hash']=f['dataset_hash']
    for pid,value in [('good','suitable'),('conditional','conditional'),('bad','unsuitable'),('missing','suitable')]:
        l['judgments'] += [judgment(reviewer=r,case_id='0',policy_id=pid,value=value,provenance='independent_review') for r in ('a','b')]
    p['predictions'][0]['resources']={'status':'completed','retrieved_ids':['good','conditional','bad'],
        'recommended_ids':['conditional','good','bad'],'suitability':{'good':'suitable','conditional':'conditional','bad':'unsuitable','missing':'unknown'}}
    return f,l,p


def test_retrieval_rank_classification_and_constraints_distinct():
    f,l,p=resource_fixture();row=matching(f,l,p)['rows'][0]
    assert row['retrieval_recall']==.5 and row['recommendation_recall_at_3']==.5
    assert row['precision']==pytest.approx(1/3) and row['conditional_rate']==pytest.approx(1/3)
    assert 0<row['ndcg_at_3']<1 and row['constraint_violations']==1
    assert row['retrieval_misses']==['missing'] and row['ranking_misses']==[]
    assert row['suitability_macro_f1']==pytest.approx((2/3+1+1)/3)


def test_unknown_never_negative_and_empty_recommendations_never_perfect():
    f,l,p=resource_fixture();l['judgments']=[r for r in l['judgments'] if r['policy_id']!='conditional']
    row=matching(f,l,p)['rows'][0]
    assert row['state']=='partial' and row['precision'] is None and row['ndcg_at_3'] is None
    assert row['precision_bounds']==[1/3,2/3] and row['unknown_returned']==['conditional']
    p['predictions'][0]['resources']['recommended_ids']=[]
    row=matching(f,l,p)['rows'][0]
    assert row['precision'] is None and row['recommendation_recall_at_3']==0 and row['correct_hold'] is None


def test_empty_valid_hold_and_failure_are_different():
    f,l,p=resource_fixture()
    for r in l['judgments']:
        if r['policy_id']:r['value']='unsuitable'
    p['predictions'][0]['resources'].update(recommended_ids=[],suitability={})
    assert matching(f,l,p)['rows'][0]['correct_hold'] is True
    p['predictions'][0]['resources']['status']='failed'
    assert matching(f,l,p)['rows'][0]['correct_hold'] is None


@pytest.mark.parametrize('kind',['duplicate','outside','unretrieved','too_many','failed'])
def test_resource_output_contracts(kind):
    f,l,p=resource_fixture();r=p['predictions'][0]['resources']
    if kind=='duplicate':r['retrieved_ids'].append('good')
    if kind=='outside':r['suitability']['outside']='suitable'
    if kind=='unretrieved':r['recommended_ids']=['missing']
    if kind=='too_many':r['retrieved_ids'].append('missing');r['recommended_ids']=list(r['retrieved_ids'])
    if kind=='failed':r['status']='failed'
    with pytest.raises(ValueError):validate_predictions(f,p)


def test_candidate_classification_does_not_erase_retrieval_failures():
    f,l,p=resource_fixture();p['predictions'][0]['resources']['suitability']['missing']='suitable'
    row=matching(f,l,p)['rows'][0]
    assert row['suitability_macro_f1']==1 and row['retrieval_recall']==.5
    assert row['suitability_class_policy']=='classes_with_reference_or_prediction_support'


def test_policy_top5_keeps_catalog_top3_and_denominators_distinct():
    f,l,p=resource_fixture();r=p['predictions'][0]['resources'];r['retrieved_ids'].append('missing');r['recommended_ids']=list(r['retrieved_ids'])
    with pytest.raises(ValueError):matching(f,l,p)
    row=matching(f,l,p,policy_candidates=True)['rows'][0]
    assert row['cutoff']==5 and row['recommendation_recall_at_5']==1 and row['precision']==.5
    assert 'recommendation_recall_at_3' not in row
    r['recommended_ids']=[]
    assert matching(f,l,p,policy_candidates=True)['rows'][0]['recommendation_recall_at_5']==0
