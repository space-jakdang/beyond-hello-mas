from datetime import date

import pytest
from pydantic import ValidationError

from backend.context.contracts import ContextFact, ContextRequest, comparable, fact_dict, resolve_region


def fact(**changes):
    return {'metric':'total_population','value':100.,'unit':'persons','geography_level':'dong',
            'geography_code':'1123051','geography_version':'provider-inventory-2024','reference_year':2024,'population':'census_residents',
            'source':'synthetic_fixture','source_url':'https://example.invalid/statistics',
            'source_hash':'a'*64,'fetched_at':'2026-10-24T00:00:00Z','status':'observed',**changes}


def request(**changes):
    return ContextRequest(**{'sgg':'11230','dong_cd':'11230510','reference_year':2024,'as_of':date(2026,10,24),**changes})


# /ship Step 7 value card
# Value: protects=provider identities require one valid parent/name match and preserve boundary provenance;
# fails_when=ambiguous or malformed provider codes are accepted or the boundary version is lost;
# why_new=existing failures stop at duplicate codes and only Gangnam has a positive fixture;
# seam=none; no_claim=synthetic provider inventory; no live KOSIS acceptance or spatial equivalence.
def test_real_boundary_collision_uses_unique_provider_inventory_instead_of_truncation():
    original=request()
    rows=[{'cd':'1123051','addr_name':'신사동'},{'cd':'1123072','addr_name':'개포3동'}]
    first=resolve_region(original,rows)
    second=resolve_region(request(dong_cd='11230511'),rows)
    assert first.provider_code=='1123051' and second.provider_code=='1123072'
    assert first.alignment=='parent_and_name_only'
    assert first.boundary_version==second.boundary_version=='2025-07-01'
    for invalid in ([], rows+[rows[0]], [{'cd':'3201051','addr_name':'신사동'}]):
        with pytest.raises(ValueError):resolve_region(original,invalid)
    with pytest.raises(ValueError):resolve_region(request(dong_cd='11230999'),rows)
    with pytest.raises(ValueError,match='ambiguous provider'):
        resolve_region(original,rows+[{'cd':'1123052','addr_name':'신사동'}])
    for code in ('11230','11230x1','112305100'):
        with pytest.raises(ValidationError):
            resolve_region(original,[{'cd':code,'addr_name':'신사동'}])
    chuncheon=resolve_region(request(sgg='32010',dong_cd='32010110'),
                             [{'cd':'3201011','addr_name':'신북읍'}])
    assert (chuncheon.sgg,chuncheon.dong_cd,chuncheon.dong_nm,chuncheon.provider_code)==(
        '32010','32010110','신북읍','3201011')
    assert chuncheon.boundary_version=='2025-07-01' and chuncheon.alignment=='parent_and_name_only'


def test_duplicate_local_names_cannot_share_a_provider_geography(monkeypatch):
    from backend.context import contracts
    geo={'features':[{'properties':{'sgg':'11230','dong_cd':code,'dong_nm':'동일동'}}
                     for code in ('11230510','11230511')]}
    monkeypatch.setattr(contracts,'boundaries',lambda:(geo,{'version':'generated-fixture'}))
    with pytest.raises(ValueError,match='ambiguous local'):
        resolve_region(request(),[{'cd':'1123051','addr_name':'동일동'}])


# /ship Step 7 value card
# Value: protects=facts reject invalid geography, unexplained missingness and malformed provenance;
# fails_when=geography, missing-reason, provenance or metadata validation is relaxed;
# why_new=existing rejection rows cover numerical and population guards but not these boundaries;
# seam=none; no_claim=contract fixtures only; no provider suppression policy or source truth is verified.
@pytest.mark.parametrize('changes',[
    {'value':True},{'value':float('nan')},{'value':-1.}, {'unit':'households'},
    {'status':'missing'}, {'value':None}, {'metric':'invented'},{'value':1.5},
    {'metric':'youth_population','age_definition':'20–34'},
    {'metric':'senior_population','age_definition':'all_ages'},
    {'published_at':'2027-01-01T00:00:00Z'},
    {'geography_code':'11230x1'},{'geography_code':'112305'},
    {'geography_code':'11230'},{'geography_level':'district'},
    {'value':None,'status':'missing'},{'value':None,'status':'missing','reason':''},
    {'value':None,'status':'suppressed'},{'value':None,'status':'suppressed','reason':''},
    {'source':'invented'},{'source':None},{'source_url':'not-a-url'},
    {'source_url':'file:///statistics'},{'source_url':None},
    {'source_hash':'a'*63},{'source_hash':'g'*64},{'source_hash':'A'*64},
    {'fetched_at':'2026-10-24T00:00:00'},
    {'published_at':'2026-10-23T00:00:00'},
    {'geography_version':''},{'population':''},{'age_definition':''},
    {'reference_year':1999},{'reference_year':2101},{'reference_year':'2024'},
    {'reference_year':2024.0},{'reference_year':True},
    {'sex':'unknown'},{'status':'unknown'},{'schema_version':'2'},{'unexpected':'value'},
])
def test_context_contract_rejects_unsafe_values_and_population_definitions(changes):
    with pytest.raises(ValidationError):ContextFact.model_validate(fact(**changes))


# /ship Step 7 value card
# Value: protects=serialized provenance and identity retain source meaning and only observed compatible facts compare;
# fails_when=identity omits provenance, defaults drift or comparison ignores definition/status differences;
# why_new=existing identity assertions omit provenance changes and comparison misses several valid dimensions;
# seam=none; no_claim=validated synthetic facts only; hashes do not establish source truth or historical availability.
def test_fact_identity_and_missingness_preserve_source_meaning():
    original=fact_dict(fact())
    assert fact_dict(fact(fetched_at='2026-10-25T00:00:00Z'))['fact_id']==original['fact_id']
    assert fact_dict(fact(value=101.))['fact_id']!=original['fact_id']
    assert fact_dict(fact(published_at='2026-10-01T00:00:00Z'))['fact_id']!=original['fact_id']
    assert fact_dict(fact(value=None,status='suppressed',reason='provider_suppressed'))['value'] is None
    assert {key:original[key] for key in ('schema_version','age_definition','sex','published_at','reason')}=={
        'schema_version':'1','age_definition':'all_ages','sex':'all','published_at':None,'reason':None}
    assert {key:original[key] for key in ('source','source_url','source_hash','fetched_at')}=={
        'source':'synthetic_fixture','source_url':'https://example.invalid/statistics',
        'source_hash':'a'*64,'fetched_at':'2026-10-24T00:00:00Z'}
    normalized=fact_dict(fact(fetched_at='2026-10-24T09:00:00+09:00',
                              published_at='2026-10-23T09:00:00+09:00'))
    assert normalized['fetched_at']=='2026-10-24T00:00:00Z'
    assert normalized['published_at']=='2026-10-23T00:00:00Z'
    for changes in ({'source':'kosis'},{'source_hash':'b'*64},
                    {'source_url':'https://example.invalid/other-statistics'},
                    {'geography_code':'1123052'},{'geography_version':'provider-inventory-2023'},
                    {'age_definition':'19-34'},{'sex':'F'},{'population':'telecom_monthly_average'}):
        assert fact_dict(fact(**changes))['fact_id']!=original['fact_id']
    for key in ('source','source_url','source_hash','fetched_at','geography_version','population'):
        payload=fact()
        del payload[key]
        with pytest.raises(ValidationError):ContextFact.model_validate(payload)
    assert comparable(original,fact_dict(fact(geography_code='1123052')))
    for changes in ({'reference_year':2023},{'geography_version':'other'},{'population':'telecom_monthly_average'},
                    {'geography_level':'district','geography_code':'11230'},
                    {'age_definition':'19-34'},{'sex':'M'},{'source':'kosis'},
                    {'value':None,'status':'missing','reason':'unavailable'}):
        assert not comparable(original,fact_dict(fact(**changes)))
    youth_total=fact_dict(fact(age_definition='19-34'))
    youth_metric=fact_dict(fact(metric='youth_population',age_definition='19-34'))
    assert not comparable(youth_total,youth_metric)
    for status in ('missing','suppressed'):
        missing=fact_dict(fact(value=None,status=status,reason='unavailable'))
        assert missing['value'] is None and missing['reason']=='unavailable' and missing['status']==status
        assert not comparable(missing,original) and not comparable(original,missing)
    with pytest.raises(ValidationError):request(reference_year=2027)


# /ship Step 7 value card
# Value: protects=requests enforce supported districts, exact dong shape, strict bounded years and required dates;
# fails_when=request input restrictions are removed or coercion accepts invalid years;
# why_new=existing requests test only district prefix and analysis-date ordering;
# seam=none; no_claim=request model only; no HTTP request handling exists in this change.
def test_scope_rejects_other_district_and_accepts_exact_youth_definition():
    with pytest.raises(ValidationError):request(dong_cd='32010010')
    assert ContextFact.model_validate(fact(metric='youth_population',age_definition='19-34')).value==100.
    for changes in ({'sgg':'11000','dong_cd':'11000010'},{'sgg':None},
                    {'dong_cd':'1123051'},{'dong_cd':'112305100'},{'dong_cd':'11230x10'},{'dong_cd':None},
                    {'reference_year':1999},{'reference_year':2101,'as_of':date(2101,1,1)},
                    {'reference_year':'2024'},
                    {'reference_year':2024.0},{'reference_year':True},{'reference_year':None},
                    {'as_of':'not-a-date'},{'as_of':None}):
        with pytest.raises(ValidationError):request(**changes)
    for key in ('sgg','dong_cd','reference_year','as_of'):
        payload=request().model_dump()
        del payload[key]
        with pytest.raises(ValidationError):ContextRequest.model_validate(payload)


# /ship Step 7 value card
# Value: protects=supported household, housing, continuous and senior definitions retain correct values and units;
# fails_when=valid units or exact senior ages reject, or valid fractional continuous values are rounded;
# why_new=existing positive assertions cover only total and youth population;
# seam=none; no_claim=synthetic metric fixtures; no KOSIS table or classification availability is established.
@pytest.mark.parametrize('metric,value,unit,age_definition',[
    ('total_households',0.,'households','all_ages'),
    ('one_person_households',1.,'households','all_ages'),
    ('total_housing',25.,'houses','all_ages'),
    ('population_density',123.5,'persons_per_km2','all_ages'),
    ('average_age',42.5,'years','all_ages'),
    ('senior_population',10.,'persons','65+'),
])
def test_supported_metric_definitions_preserve_valid_values(metric,value,unit,age_definition):
    result=fact_dict(fact(metric=metric,value=value,unit=unit,age_definition=age_definition))
    assert (result['metric'],result['value'],result['unit'],result['age_definition'])==(
        metric,value,unit,age_definition)
