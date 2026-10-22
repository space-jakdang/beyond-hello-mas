from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from backend.policy.analogues import research,AnalogueRequest


def fixture():
    policies=[{'id':'a','scope':'chuncheon','title':'관계 지원','url':'https://example.org/policy/a','support':'방문 지원','eligibility':'거주 주민'},
              {'id':'b','scope':'seoul','title':'관계 지원','url':'https://example.org/policy/b'}]
    coverage={'source_complete':True,'stale':False,'last_attempt':{'status':'success'}}
    def search(query):
        assert 'gangnam' not in query.scopes and query.per_page==100 and query.query=='관계'
        return {'items':policies,'total':6,'next_page':2,'coverage':coverage}
    service=SimpleNamespace(search=search,detail=lambda id:{'status':'live' if id=='a' else 'cached','policy':next(p for p in policies if p['id']==id),'checked_at':'2026-10-22T00:00:00Z'})
    return service,coverage


def test_analogue_requires_live_source_and_never_grants_local_eligibility():
    service,_=fixture()
    result=research(service,{'local_scope':'gangnam','query':'관계','target_group':'청년'})
    assert result['status']=='evidence_available' and len(result['analogues'])==1
    source=result['analogues'][0]['source']
    assert source['fields']['support']=='방문 지원' and source['local_eligibility']=='not_established'
    assert result['analogues'][0]['comparison']['target_group_fit']=='not_established'
    assert result['search_exhausted'] is False and result['absence_established'] is False
    assert result['next_page']==2 and result['total_matches']==6
    assert result['detail_checks'][1]['usable'] is False
    assert not result['allocation_performed']


def test_stale_absent_or_unlinked_examples_do_not_establish_evidence():
    service,coverage=fixture();coverage['stale']=True
    request={'local_scope':'gangnam','query':'관계','target_group':'청년'}
    assert research(service,request)['status']=='needs_evidence'
    service.detail=lambda id:{'status':'live','policy':{'id':id,'scope':'chuncheon','title':'정책','url':None},'checked_at':'now'}
    assert research(service,request)['analogues']==[]
    with pytest.raises(ValidationError):AnalogueRequest(**{**request,'query':' '})
    with pytest.raises(ValidationError):AnalogueRequest(**{**request,'local_scope':'invented'})


def test_scope_mismatch_and_unrecorded_refresh_are_not_accepted():
    service,coverage=fixture()
    request={'local_scope':'gangnam','query':'관계','target_group':'청년'}
    coverage['last_attempt']=None
    assert research(service,request)['status']=='needs_evidence'
    service.detail=lambda id:{'status':'live','policy':{'id':id,'scope':'gangnam','title':'정책','url':'https://example.org'},'checked_at':'now'}
    result=research(service,request)
    assert not result['analogues'] and all(c['reason']=='scope_mismatch' for c in result['detail_checks'])


def test_shortlist_prioritizes_target_title_over_incidental_legal_text():
    service,_=fixture();seen=[]
    rows=[{'id':str(i),'scope':'central','title':'선박 지원','summary':'관계 법령','eligibility':'선주'} for i in range(6)]
    rows.append({'id':'youth','scope':'seoul','title':'청년 사회관계 지원','summary':'고립 청년 관계 회복','eligibility':'청년'})
    service.search=lambda q:{'items':rows,'total':7,'next_page':None,'coverage':{'source_complete':True,'stale':False,'last_attempt':{'status':'success'}}}
    def detail(id):
        seen.append(id)
        return {'status':'live','policy':{**next(p for p in rows if p['id']==id),'url':'https://example.org/'+id},'checked_at':'2026-10-22T00:00:00Z'}
    service.detail=detail
    result=research(service,{'local_scope':'gangnam','query':'관계','target_group':'청년'})
    assert seen[0]=='youth' and len(seen)==5
    assert result['candidates_considered']==7 and result['representative_sample'] is False
    assert result['analogues'][0]['comparison']['target_group_fit']=='not_established'
