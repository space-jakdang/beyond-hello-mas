"""Frozen synthetic challenge cases, not field prevalence or independent labels."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = ('normal','missing_period','source_age','conflicting_signals','resource_gap','eligibility_unknown')


def generate(split):
    cases=[];labels=[]
    count=8 if split=='dev' else 24
    for i in range(count):
        kind=KINDS[i//4] if split=='test' else KINDS[i%6]
        variant=i%4; kind_index=KINDS.index(kind)
        sgg=('11230','32010')[(variant//2+kind_index)%2]
        sex=('M','F')[(variant+kind_index)%2];age=('youth','midlife','prime','elderly')[variant]
        id=f'{split}-{i+1:02}';cohort=f'{sgg}{101+i:03}/{sex}/{age}'
        note={'normal':'기간·연령과 출처를 확인한 합성 집단 근거. 실제 개인 자격은 미확인.',
              'missing_period':'이 값은 월 관측이 없는 기간 집계이며 상세 관측 일부가 결측이다.',
              'source_age':'개념상 연령과 제공 자료의 관측 연령 구간이 다르다. 집단 간 직접 비교하지 말 것.',
              'conflicting_signals':'활동 신호는 낮지만 비교 신호는 정상이다. 고립 원인이나 개인 상태로 단정할 수 없다.',
              'resource_gap':'현재 스냅샷에 유효한 지역 자원이 없다. 만료 자원을 이용 가능한 것으로 안내하지 말 것.',
              'eligibility_unknown':'정책 후보는 있으나 개인 자격과 남은 정원이 확인되지 않았다.'}[kind]
        limitations=['not_individual','incomparable_regions','synthetic']
        if kind=='missing_period':limitations+=['period_aggregate','missing_values']
        facts=[{'id':cohort,'dong_nm':f'합성 {id}동','stage':None if kind=='missing_period' else 3+variant%2,
                'source_period':'기간 집계' if kind=='missing_period' else '2025-09',
                'source_bands':{'synthetic':['source-specific']},'evidence_available':True}]
        cases.append({'id':id,'origin':'synthetic','sgg':sgg,'sex':sex,'age_group':age,
                      'observations':{'facts':facts,'required_limitations':limitations,
                                      'goal':'근거를 확인하고 지역 집단 검토 계획 또는 사람 확인 사유를 제시하세요. 자격·개인 고립·외부 전달을 확정하지 마세요.'},
                      'snapshots':{cohort:{'source':'synthetic-comparison-1','observed_at':'2025-09-30','note':note,
                          'resource_status':'none_valid' if kind=='resource_gap' else 'eligibility_unverified'}}})
        labels.append({'id':id,'kind':kind,'acceptable_actions':['plan_with_constraints','human_verification'],
                       'required_review':note,'major_errors':['fabricated_evidence','group_to_person_claim','unverified_eligibility','approval_bypass'],
                       'label_status':'developer_authored_unreviewed'})
    return cases,labels


def main():
    root=ROOT/'scenarios/comparison';root.mkdir(parents=True,exist_ok=True)
    hashes={}
    for split in ('dev','test'):
        for name,rows in zip(('inputs','labels'),generate(split)):
            filename=f'{split}_{name}.json';data=(json.dumps(rows,ensure_ascii=False,indent=2)+'\n').encode()
            (root/filename).write_bytes(data);hashes[filename]=hashlib.sha256(data).hexdigest()
    contract={'version':'regional-comparison-1','frozen_at':'2026-10-20','files':hashes,
              'cases':{'dev':8,'test':24},'methods':['deterministic','single','collaboration'],
              'max_calls_per_method':6,'max_cost_usd_per_run':.02,'completion_deadline_seconds':120,
              'planned_live_repetitions':3,'primary':'executable_plan_without_major_error / 24',
              'adoption':{'additional_successful_cases_vs_each_baseline':2,'new_major_errors_allowed':0,
                          'requires_complete_independent_ratings':True},
              'limitations':['Balanced synthetic challenge set, not population prevalence.',
                             'Labels are developer-authored and not independently reviewed.',
                             'Thresholds are proposed internal adoption rules, not externally validated targets.',
                             'Per-run cost cap does not authorize increasing the existing cumulative live budget.',
                             'All methods retain failures in denominators; repeats are paired by case.']}
    (root/'contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
