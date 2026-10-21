from copy import deepcopy
import json
import subprocess
import sys
import pytest
from eval.quality_contracts import freeze, load_frozen, readiness_report
from eval.prepare_quality import read_judgments


def dataset():
    return {'id': 'challenge', 'version': '1', 'cases': [{
        'id': 'dong-1', 'family_id': 'source-1', 'region': 'sample-region',
        'neighborhood': 'sample-dong', 'cohort': 'all', 'period': '2026-01',
        'methodology': 'provisional-v1', 'split': 'test', 'source': 'synthetic',
        'policy_as_of': '2026-01-01', 'facts': {'isolation_index': 0.4},
        'policies': {'p1': {'description': 'Synthetic social support example'}}}]}


def labels(frozen):
    return {'dataset_hash': frozen['dataset_hash'], 'reviewers': [
        {'id': r, 'expertise': 'fixture reviewer', 'development_participant': False}
        for r in ['a', 'b', 'c']], 'judgments': []}


def judgment(reviewer='a', value='3', **overrides):
    return {'case_id': 'dong-1', 'policy_id': None, 'reviewer': reviewer, 'value': value,
        'reason': 'fixture only', 'reviewed_at': '2026-02-01',
        'provenance': 'synthetic_reference', 'policy_as_of': '2026-01-01',
        'adjudication': False, **overrides}


def test_missing_is_not_perfect_and_unknown_is_not_missing():
    frozen = freeze(dataset()); data = labels(frozen)
    report = readiness_report(frozen, data)
    assert report['metrics'] is None and report['status'] == 'not_evaluated'
    assert report['readiness']['missing'] == 2
    data['judgments'] = [judgment(value='unknown')]
    report = readiness_report(frozen, data)
    assert report['readiness']['unknown'] == 1 and report['readiness']['missing'] == 1


def test_hash_and_family_leakage_rejected():
    frozen = freeze(dataset()); modified = deepcopy(frozen)
    modified['dataset']['cases'][0]['facts']['isolation_index'] = 0.9
    with pytest.raises(ValueError, match='changed'): load_frozen(modified)
    data = dataset(); clone = deepcopy(data['cases'][0])
    clone.update(id='another-month', period='2026-02', split='dev')
    data['cases'].append(clone)
    with pytest.raises(ValueError, match='crosses'): freeze(data)
    data['cases'][1]['split'] = 'test'
    assert freeze(data)


def test_disagreement_requires_separate_adjudicator_and_keeps_provenance():
    frozen = freeze(dataset()); data = labels(frozen)
    data['judgments'] = [judgment(), judgment('b', '4')]
    assert readiness_report(frozen, data)['readiness']['disagreements'] == 1
    data['judgments'].append(judgment('c', '4', adjudication=True))
    ref = readiness_report(frozen, data)['references'][0]
    assert ref['value'] == '4' and ref['adjudicated'] and not ref['independent']
    data['judgments'][-1]['reviewer'] = 'a'
    with pytest.raises(ValueError, match='adjudicator'): readiness_report(frozen, data)


@pytest.mark.parametrize('override', [
    {'value': '6'}, {'policy_id': 'missing'}, {'case_id': 'missing'},
    {'policy_as_of': '2026-01-02'}, {'reviewer': 'missing'},
    {'provenance': 'observed_outcome'}, {'value': 'suitable'},
])
def test_invalid_references_rejected(override):
    frozen = freeze(dataset()); data = labels(frozen)
    data['judgments'] = [judgment(**override)]
    with pytest.raises(ValueError): readiness_report(frozen, data)


def test_independent_requires_two_non_developer_reviewers():
    frozen = freeze(dataset()); data = labels(frozen)
    data['judgments'] = [judgment(provenance='independent_review')]
    assert not readiness_report(frozen, data)['references'][0]['independent']
    data['judgments'].append(judgment('b', provenance='independent_review'))
    assert readiness_report(frozen, data)['references'][0]['independent']
    data['reviewers'][1]['development_participant'] = True
    with pytest.raises(ValueError, match='developer'): readiness_report(frozen, data)
    data['reviewers'][1]['development_participant'] = False
    data['dataset_hash'] = 'wrong'
    with pytest.raises(ValueError, match='different dataset'): readiness_report(frozen, data)


def test_csv_import_and_cli_preserve_inputs_and_keep_labels_separate(tmp_path):
    csv_path = tmp_path / 'ratings.csv'
    csv_path.write_text('case_id,policy_id,reviewer,value,reason,reviewed_at,provenance,policy_as_of,adjudication\n'
        'dong-1,,a,3,fixture,2026-02-01,synthetic_reference,2026-01-01,false\n')
    assert read_judgments(csv_path)[0]['adjudication'] is False
    original = tmp_path / 'dataset.json'; original.write_text(json.dumps(dataset()))
    before = original.read_bytes()
    result = subprocess.run([sys.executable, '-m', 'eval.prepare_quality', str(original), '--output-root', str(tmp_path/'out')], capture_output=True, text=True, check=True)
    from pathlib import Path
    folder = Path(result.stdout.strip())
    assert original.read_bytes() == before
    assert 'judgments' not in (folder/'inputs.json').read_text()
    assert json.loads((folder/'readiness.json').read_text())['metrics'] is None


def test_blind_packet_mapping_is_bound_and_labels_not_exposed():
    from eval.quality_contracts import blind_packet, unblind_judgments
    frozen = freeze(dataset())
    packet, key = blind_packet(frozen)
    assert 'family_id' not in str(packet) and 'split' not in str(packet)
    blind_id = packet['items'][0]['blind_id']
    result = unblind_judgments(frozen, key, [judgment(case_id=blind_id)])
    assert result[0]['case_id'] == 'dong-1'
    with pytest.raises(ValueError, match='unknown blind'):
        unblind_judgments(frozen, key, [judgment(case_id='not-in-packet')])
    key['dataset_hash'] = 'another-dataset'
    with pytest.raises(ValueError, match='mismatch'):
        unblind_judgments(frozen, key, [])


def test_reviewer_whitespace_normalized_and_blank_rejected():
    frozen = freeze(dataset()); data = labels(frozen)
    data['reviewers'][0]['id'] = ' a '
    data['judgments'] = [judgment()]
    assert readiness_report(frozen, data)['references'][0]['state'] == 'resolved'
    data['reviewers'][0]['id'] = ' '
    with pytest.raises(ValueError): readiness_report(frozen, data)


def test_csv_missing_columns_and_cli_blind_import(tmp_path):
    from pathlib import Path
    from eval.quality_contracts import blind_packet
    path = tmp_path/'ratings.csv'; path.write_text('reviewer,value\na,3\n')
    with pytest.raises(ValueError, match='CSV missing columns'): read_judgments(path)
    frozen = freeze(dataset()); data = labels(frozen); packet, key = blind_packet(frozen)
    assert set(packet['items'][0]) == {'blind_id','source','period','methodology','policy_as_of','facts','policies'}
    blind_id = packet['items'][0]['blind_id']
    path.write_text('case_id,policy_id,reviewer,value,reason,reviewed_at,provenance,policy_as_of,adjudication\n'
        + ''.join(f'{blind_id},,{r},3,fixture,2026-02-01,independent_review,2026-01-01,false\n' for r in ['a','b']))
    for name, body in [('inputs', frozen), ('labels', data), ('key', key)]:
        (tmp_path/f'{name}.json').write_text(json.dumps(body))
    result = subprocess.run([sys.executable,'-m','eval.prepare_quality',str(tmp_path/'inputs.json'),
        '--labels',str(tmp_path/'labels.json'),'--judgments',str(path),'--key',str(tmp_path/'key.json'),
        '--output-root',str(tmp_path/'out')],capture_output=True,text=True,check=True)
    folder = Path(result.stdout.strip())
    assert json.loads((folder/'readiness.json').read_text())['readiness']['independent_resolved'] == 1
    assert not (folder/'private-key.json').exists()
    assert json.loads((folder/'import-key.json').read_text()) == key
    assert json.loads((folder/'labels.json').read_text())['judgments'][0]['case_id'] == 'dong-1'
