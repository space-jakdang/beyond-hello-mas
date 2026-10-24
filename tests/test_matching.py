from datetime import date
from pathlib import Path
import random

import pytest
from pydantic import ValidationError

from backend.tools.catalog import load_catalog
from backend.tools.matching import MatchRequest, map_intensity, map_needs, match
from backend.tools.staging import classify
from scripts.generate_segments import generate


def catalog():
    return load_catalog(Path('data/sample/resources.csv'))


def request(**changes):
    return MatchRequest(**{'sgg': '11230', 'age_min': 20, 'age_max': 29, 'needs': ['relationship'],
                           'intensity': 'low', 'as_of': date(2026, 10, 18), **changes})


def test_hand_labeled_order_and_jurisdiction():
    resources = catalog()
    result = match(resources, request())
    assert [r['id'] for r in result['recommendations']] == ['synthetic-01', 'synthetic-02', 'synthetic-03']
    reasons = {r['id']: r['reasons'] for r in result['excluded']}
    assert reasons['synthetic-04'] == ['jurisdiction']
    assert 'intensity' in reasons['synthetic-06']
    assert result['shortfall'] == 0
    random.Random(42).shuffle(resources)
    assert match(resources, request()) == result
    assert [r['id'] for r in match(resources, request(sgg='32010'))['recommendations']] == [
        'synthetic-01', 'synthetic-04', 'synthetic-05']


def test_age_qualification_expiry_and_partial_supply():
    base = catalog()[0]
    resource = base.model_copy(update={'age_min': 20, 'age_max': 29, 'eligibility_tags': ['resident']})
    assert match([resource], request())['shortfall'] == 3
    assert match([resource], request(eligibility={'resident': None}))['shortfall'] == 3
    assert match([resource], request(eligibility={'resident': False}))['shortfall'] == 3
    assert match([resource], request(eligibility={'resident': True}))['shortfall'] == 2
    assert match([resource], request(age_min=19, eligibility={'resident': True}))['shortfall'] == 3
    assert match([resource], request(age_max=30, eligibility={'resident': True}))['shortfall'] == 3
    for changes in ({'active': False}, {'valid_until': date(2025, 12, 31)}, {'eligibility': 'unknown eligibility'}):
        assert match([base.model_copy(update=changes)], request())['shortfall'] == 3
    assert match([], request())['recommendations'] == []
    assert match([base], request(as_of=date(2024, 1, 1)))['shortfall'] == 3
    assert match([base.model_copy(update={'valid_until': date(2026,10,18)})], request())['shortfall'] == 2


def test_invalid_catalog_and_request(tmp_path):
    with pytest.raises(ValueError, match='duplicate resource'):
        match([catalog()[0]] * 2, request())
    with pytest.raises(ValueError, match='jurisdiction'):
        match([catalog()[0].model_copy(update={'jurisdiction': ['unknown']})], request())
    with pytest.raises(ValueError, match='unsupported'):
        match(catalog(), request(sgg='99999'))
    with pytest.raises(ValueError, match='age range'):
        match(catalog(), request(age_min=50, age_max=20))
    for text in ('id,name\nx,y\n', Path('data/sample/resources.csv').read_text().replace('[""KR""]', 'bad-json')):
        path = tmp_path / 'bad.csv'
        path.write_text(text)
        with pytest.raises((ValueError, ValidationError)):
            load_catalog(path)


def test_classification_to_matching_and_evidence():
    result = classify(generate())['segments'][0]
    needs = map_needs(['activity_deficit'])
    assert map_needs(['unknown']) == []
    assert map_intensity(None) is None
    response = match(catalog(), request(needs=needs, intensity=map_intensity(result['stage'])))
    assert response['metadata']['provisional']
    originals = {r.id: r.model_dump(mode='json') for r in catalog()}
    for recommendation in response['recommendations']:
        assert recommendation == originals[recommendation['id']]


def test_regional_unknown_is_conditional_but_false_and_known_mismatches_are_excluded():
    base = catalog()[0].model_copy(update={'eligibility_tags':['resident']})
    unknown = match([base], request(), regional_ages=[(20,29)])['recommendations'][0]
    assert unknown['candidate_status'] == 'conditional'
    assert unknown['condition_checks']['eligibility:resident'] == 'unknown'
    assert unknown['unknown_conditions'] == ['eligibility:resident']
    assert match([base], request())['recommendations'] == []
    rejected = match([base], request(eligibility={'resident':False}), regional_ages=[(20,29)])
    assert not rejected['recommendations']
    assert rejected['excluded'][0]['reasons'] == ['eligibility_mismatch:resident']
    confirmed = match([base], request(eligibility={'resident':True}), regional_ages=[(20,29)])
    assert confirmed['recommendations'][0]['candidate_status'] == 'matched'
    assert confirmed['metadata']['policy_version']=='regional-candidates-1'
    assert confirmed['metadata']['input_hash']!=match([base],request(eligibility={'resident':True}))['metadata']['input_hash']
    for change, reason in [({'jurisdiction':['32010']},'jurisdiction'),
                           ({'active':False},'inactive_or_expired'),
                           ({'valid_until':date(2026,10,17)},'inactive_or_expired'),
                           ({'age_min':65},'age'),({'needs':['health']},'needs')]:
        result = match([base.model_copy(update=change)],request(),regional_ages=[(20,29)])
        assert not result['recommendations'] and reason in result['excluded'][0]['reasons']
    free_text = catalog()[0].model_copy(update={'eligibility':'담당자 확인 필요'})
    assert match([free_text],request(),regional_ages=[(20,29)])['recommendations'][0]['unknown_conditions'] == ['unstructured_eligibility']
    assert not match([],request(),regional_ages=[(20,29)])['recommendations']


def test_regional_age_union_never_fills_gaps_or_approves_the_entire_cohort():
    base = catalog()[0]
    req = request(age_min=20,age_max=69)
    narrow = base.model_copy(update={'age_min':25,'age_max':34})
    row = match([narrow],req,regional_ages=[(20,29),(60,69)])['recommendations'][0]
    assert row['candidate_status']=='conditional' and row['age_coverage']=='partial'
    assert row['eligible_age_ranges']==[(25,29)]
    assert row['condition_checks']['age']=='unknown'
    assert match([base],req,regional_ages=[(20,29),(60,69)])['metadata']['input_hash']!=match([base],req,regional_ages=[(20,69)])['metadata']['input_hash']
    gap = base.model_copy(update={'age_min':40,'age_max':50})
    assert not match([gap],req,regional_ages=[(20,29),(60,69)])['recommendations']
    assert not match([narrow],req)['recommendations']
    for ages in ([],[(19,29)],[(30,20)]):
        with pytest.raises(ValueError,match='regional age'):
            match([base],req,regional_ages=ages)
    with pytest.raises(ValidationError):
        request(regional_ages=[(20,29)])
