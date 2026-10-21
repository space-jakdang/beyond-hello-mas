from copy import deepcopy
import pytest
from backend.policy.design_contracts import Gap,validate_draft


def fixture():
    gap={'state':'no_verified_candidates','catalog_shortfall':3,'search_scope':['gangnam'],'checked_at':'2026-10-21',
         'complete_within_scope':True,'limitations':['only registered source and query']}
    source={'policy_id':'p','title':'연결 지원','scope':'another-region','source_url':'https://example.org/p','checked_at':'2026-10-21',
            'fields':{'support':'주 1회 전화 지원'}}
    draft={'status':'draft','title':'지역 연결 시범안','problem_evidence_ids':['obs'],'target_group':'청년 집단',
        'proposed_service':'접근 수단을 확인한 뒤 전화 또는 대면 시범 운영',
        'adaptations':[{'source_policy_ids':['p'],'local_difference':'지역의 이동 여건은 확인 필요','proposed_change':'방문 거점 검토','verification_needed':['이동 자료']}],
        'citations':[{'policy_id':'p','field':'support','quote':'주 1회 전화 지원'}],
        'operating_steps':['수요 확인','시범 검토'],'required_roles':['담당자'],'feasibility_checks':['예산 확인','법적 근거 검토'],
        'equity_risks':['낙인 가능성'],'reviewer_questions':['대상 선정 기준은?'],
        'evaluation':{'outcome':'연결 서비스 이용 지속','baseline_needed':'시범 전 측정','comparison_method':'비교 집단 검토',
            'observation_period':'자료 확보 후 합의','success_criterion_to_agree':'담당자와 사전 합의','stop_criterion_to_agree':'불편 신고 기준 합의'}}
    return draft,gap,[source]


def test_verified_adaptation_stays_separate_from_existing_benefit_and_execution():
    draft,gap,sources=fixture();result=validate_draft(draft,['obs'],gap,sources)
    assert result['review_status']=='pending' and not result['draft']['allocation_performed']
    assert result['analogues'][0]['local_eligibility']=='not_established'
    assert not result['all_policies_known'] and result['version']


@pytest.mark.parametrize('kind',['incomplete','unknown_fact','invented_quote','uncited','no_analogue','approved','budget','duplicate'])
def test_unverified_design_cannot_be_promoted(kind):
    draft,gap,sources=fixture()
    if kind=='incomplete':gap['complete_within_scope']=False
    if kind=='unknown_fact':draft['problem_evidence_ids']=['invented']
    if kind=='invented_quote':draft['citations'][0]['quote']='매일 지원'
    if kind=='uncited':draft['citations']=[]
    if kind=='no_analogue':draft['adaptations']=[]
    if kind=='approved':draft['status']='approved'
    if kind=='budget':draft['budget_confirmed']=True
    if kind=='duplicate':sources.append(deepcopy(sources[0]))
    with pytest.raises(ValueError):validate_draft(draft,['obs'],gap,sources)


def test_incomplete_search_retains_request_for_evidence():
    draft,gap,sources=fixture();gap.update(state='search_incomplete',complete_within_scope=False)
    draft.update(status='needs_evidence',adaptations=[],citations=[])
    assert validate_draft(draft,['obs'],gap,[])['draft']['status']=='needs_evidence'
