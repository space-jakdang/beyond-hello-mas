from copy import deepcopy
import pytest
from scripts.generate_workflow_cases import generate,write_dataset
from eval.run_workflow import evaluate
from backend.tools.region_stage import classify


def test_synthetic_cases_are_reproducible_and_labels_separated(tmp_path):
    data=generate()
    assert data==generate() and data['input_hash']!=generate(2)['input_hash']
    assert all('stage' not in r and 'expected' not in r for r in data['inputs'])
    assert {r['family'] for r in data['inputs'] if r['split']=='development'}.isdisjoint({r['family'] for r in data['inputs'] if r['split']=='test'})
    write_dataset(tmp_path/'cases')
    assert (tmp_path/'cases/inputs.json').exists() and (tmp_path/'cases/labels.json').exists()
    with pytest.raises(FileExistsError):write_dataset(tmp_path/'cases')
    result=evaluate(data)
    assert result['contract_passed'] and result['reproducible']
    assert result['contract']['resource_constraints']['recommended']>0
    assert result['contract']['resource_constraints']['violations']==0
    assert result['external_classification_validity'] is None and result['collaboration_effect'] is None
    assert result['adoption_decision']=='not_evaluated'


def test_wrong_classifier_missing_predictions_and_failures_do_not_pass():
    def wrong(rows):
        result=classify(rows)
        for row in result['segments']:row['stage']=None
        return result
    result=evaluate(generate(),wrong)
    assert not result['contract_passed']
    assert result['contract']['classification_mixed_contract']['missing_predictions']==30
    assert result['contract']['classification_mixed_contract']['grade_agreement']['value']==0
    assert result['contract']['classification_mixed_contract']['ordinal_mae']['value'] is None
    assert result['contract']['classification_mixed_contract']['priority_miss']['value']==1
    assert result['contract']['classification_mixed_contract']['correct_abstention']['value']==1
    def fails(rows):raise RuntimeError('fixture')
    result=evaluate(generate(),fails)
    assert len(result['results'])==36 and all(r['error']=='RuntimeError' for r in result['results'])
    assert not result['contract_passed']
    assert result['contract']['resource_constraints']['recommendation_coverage']['denominator']==18
    corrupt=deepcopy(generate());corrupt['labels'][0]['stage']=5
    with pytest.raises(ValueError,match='checksum'):evaluate(corrupt)


def test_wrong_nonmissing_grade_and_input_tampering_are_detected():
    def wrong(rows):
        output=classify(rows)
        for row in output['segments']:row['stage']=1
        return output
    result=evaluate(generate(),wrong)
    assert not result['contract_passed']
    assert result['contract']['classification_mixed_contract']['ordinal_mae']['value']>0
    corrupt=deepcopy(generate());corrupt['inputs'][0]['segment']['value']=.99
    with pytest.raises(ValueError,match='checksum'):evaluate(corrupt)
    assert evaluate(generate(13))['contract_passed']
