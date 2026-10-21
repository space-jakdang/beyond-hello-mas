from copy import deepcopy
import pytest
from eval.quality_contracts import freeze
from eval.quality_metrics import classification, validate_predictions
from test_quality_contracts import dataset, labels, judgment


def fixture(truth=(1,2,3,4,5), predicted=(1,2,3,4,5)):
    body=dataset();base=body['cases'][0];body['cases']=[]
    for i in range(len(truth)):
        row=deepcopy(base);row.update(id=str(i),neighborhood=f'dong-{i}',family_id=f'family-{i}');body['cases'].append(row)
    frozen=freeze(body);ratings=labels(frozen)
    ratings['judgments']=[judgment(reviewer=r,value=str(t),case_id=str(i),provenance='independent_review') for i,t in enumerate(truth) for r in ('a','b')]
    predictions={'dataset_hash':frozen['dataset_hash'],'model':'test-fixture','version':'1','method':'rules',
        'predictions':[{'case_id':str(i),'grade':g,'status':'predicted' if g else 'abstained'} for i,g in enumerate(predicted)]}
    return frozen,ratings,predictions


def test_hand_calculated_confusion_macro_and_abstention():
    f,l,p=fixture((1,2,4,5),(1,4,None,5));g=classification(f,l,p)['groups'][0]
    assert g['confusion'][3][5]==1 and g['confusion'][1][3]==1
    assert g['macro_f1']==.5  # classes 1,2,4,5: 1,0,0,1
    assert g['priority_recall']==.5 and g['priority_precision']==.5
    assert g['coverage']==.75 and g['mae']==pytest.approx(2/3)
    assert len(g['errors'])==2


def test_all_high_not_perfect_and_missing_predictions_stay_in_denominator():
    f,l,p=fixture(predicted=(5,5,5,5,5));g=classification(f,l,p)['groups'][0]
    assert g['priority_recall']==1 and g['priority_precision']==.4 and g['flag_rate']==1
    assert g['macro_f1']<.1
    p['predictions']=[];g=classification(f,l,p)['groups'][0]
    assert g['priority_recall']==0 and g['priority_precision'] is None
    assert g['macro_f1']==0 and g['mae'] is None and g['missing_predictions']==5
    l['judgments']=[];g=classification(f,l,p)['groups'][0]
    assert g['macro_f1'] is None and g['missing_labels']==5


def test_unknown_non_independent_and_scope_not_pooled():
    f,l,p=fixture();l['judgments'][0]['value']='unknown';l['judgments'][1]['value']='unknown'
    for row in l['judgments'][2:4]:row['provenance']='rule_oracle'
    g=classification(f,l,p,{'0','1','2'})['groups'][0]
    assert g['unknown_labels']==1 and g['non_independent_labels']==1 and g['reference_count']==1
    assert g['priority_recall'] is None


@pytest.mark.parametrize('change', ['duplicate','unknown','hash','bool','range','status'])
def test_prediction_boundaries(change):
    f,l,p=fixture()
    if change=='duplicate':p['predictions'].append(p['predictions'][0])
    if change=='unknown':p['predictions'][0]['case_id']='outside'
    if change=='hash':p['dataset_hash']='changed'
    if change=='bool':p['predictions'][0]['grade']=True
    if change=='range':p['predictions'][0]['grade']=6
    if change=='status':p['predictions'][0]['status']='failed'
    with pytest.raises(ValueError):validate_predictions(f,p)


def test_source_and_methodology_groups_never_pool():
    f,l,p=fixture((1,2,4),(1,2,None))
    body=deepcopy(f['dataset']);body['cases'][1]['source']='observed';body['cases'][2]['methodology']='another-v2'
    f=freeze(body);l['dataset_hash']=f['dataset_hash'];p['dataset_hash']=f['dataset_hash']
    groups=classification(f,l,p)['groups']
    assert len(groups)==3 and all(g['reference_count']==1 for g in groups)
    assert next(g for g in groups if g['methodology']=='another-v2')['priority_recall']==0
    assert next(g for g in groups if g['source']=='observed')['macro_f1']==1
