from datetime import date
import pytest
from backend.tools.catalog import load_catalog
from backend.tools.matching import MatchRequest,match
from scripts.import_resources import merge


def provided(id='S02',**changes):
    return {'id':id,'지역':'서울','자원명':'synthetic program','운영':'synthetic provider','유형':'관계·상담',
        '최소단계':'2','최대단계':'4','체납연계':'N','나이하한':'19','나이상한':'64',
        '이용방식':'synthetic application','연락':'not real','확인상태':'확인','비고':'synthetic fixture',**changes}


def test_merge_retains_both_sources_and_checked_access():
    from pathlib import Path
    existing=load_catalog(Path('data/catalog/curated-20261018-1/resources.csv'))
    result=merge([provided(),provided('N01'),provided('NEW-A'),provided('NEW-B')],existing,'synthetic')
    assert len(result)==32
    row=next(r for r in result if r.id=='seoul-120')
    original=next(r for r in existing if r.id==row.id)
    assert len(row.provenance)==2 and row.source_url==original.source_url
    assert row.eligibility_tags==original.eligibility_tags and row.stage_min==2
    assert row.collected_at==original.collected_at
    assert row.provenance[0]['resource']['catalog_version']==original.catalog_version
    with pytest.raises(ValueError,match='duplicate'):merge([provided(),provided()],existing,'synthetic')


def test_stage_age_eligibility_and_parallel_arrears_axis():
    rows=[provided('A'),provided('B',유형='부채',체납연계='Y'),provided('C',최소단계='5',최대단계='5')]
    resources=merge(rows,[],'synthetic')
    request=MatchRequest(sgg='11230',age_min=30,age_max=30,needs=['relationship'],intensity='high',stage=3,arrears=True,as_of=date(2026,10,19))
    assert not match(resources,request)['recommendations']
    request.eligibility={f'confirmed:{r.id}':True for r in resources}
    result=match(resources,request)
    assert {r['id'] for r in result['recommendations']}=={'seohee-A','seohee-B'}
    assert 'stage' in next(r['reasons'] for r in result['excluded'] if r['id']=='seohee-C')
    assert not match(resources,request.model_copy(update={'age_min':70,'age_max':70}))['recommendations']
    assert [r['id'] for r in match(resources,request.model_copy(update={'arrears':False}))['recommendations']]==['seohee-A']


from tests.test_admin import person_service, personal
from tests.test_graph import service


def test_case_flags_add_parallel_needs_without_turning_eviction_into_arrears(person_service,monkeypatch):
    captured=[]
    def matching(resources,request):
        captured.append(request)
        return {'recommendations':[]}
    monkeypatch.setattr('backend.graph.match',matching)
    for flags in ({'arrears_rent':True},{'eviction_risk':True}):
        run=person_service.start(personal(admin_flags=flags,responses={'synthetic-contract-fixture':{'case':999}}))
        assert run.status=='awaiting_approval'
    assert set(captured[0].needs)=={'relationship','economic','housing'} and captured[0].arrears
    assert set(captured[1].needs)=={'relationship','housing'} and not captured[1].arrears
