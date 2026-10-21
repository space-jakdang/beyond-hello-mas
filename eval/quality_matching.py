"""Separate retrieval, rank and suitability against a fixed, judged policy pool."""
from math import log2
from statistics import mean
from eval.quality_contracts import load_frozen, resolve_labels
from eval.quality_metrics import validate_predictions, ratio


def matching(frozen, labels, predictions, case_ids=None, policy_candidates=False):
    dataset=load_frozen(frozen);data=validate_predictions(frozen,predictions,policy_candidates)
    cutoff=5 if policy_candidates else 3
    if not any(p.resources is not None for p in data.predictions):return None
    refs={(r['case_id'],r['policy_id']):r for r in resolve_labels(frozen,labels)['references'] if r['policy_id'] is not None}
    outputs={p.case_id:p.resources for p in data.predictions};rows=[]
    classes=['suitable','conditional','unsuitable']
    for case in dataset.cases:
        if case_ids is not None and case.id not in case_ids:continue
        output=outputs.get(case.id)
        retrieved=output.retrieved_ids if output else []
        recommended=output.recommended_ids if output else []
        truth={pid:r['value'] for pid in case.policies if (r:=refs[(case.id,pid)])['independent'] and r['state']=='resolved'}
        relevant={pid for pid,value in truth.items() if value=='suitable'}
        complete=bool(case.policies) and len(truth)==len(case.policies)
        unknown_returned=[pid for pid in recommended if pid not in truth]
        suitable=sum(truth.get(pid)=='suitable' for pid in recommended)
        conditional=sum(truth.get(pid)=='conditional' for pid in recommended)
        gains={'suitable':2,'conditional':1,'unsuitable':0}
        ideal=sorted((gains[v] for v in truth.values()),reverse=True)[:cutoff]
        idcg=sum(g/log2(i+2) for i,g in enumerate(ideal))
        ndcg=(ratio(sum(gains[truth[pid]]/log2(i+2) for i,pid in enumerate(recommended)),idcg)
              if complete and not unknown_returned else None)
        matrix=[[0]*4 for _ in classes]
        for pid,value in truth.items():
            predicted=output.suitability.get(pid,'unknown') if output else 'unknown'
            matrix[classes.index(value)][classes.index(predicted) if predicted in classes else 3]+=1
        fs=[]
        for i in range(3):
            support=sum(matrix[i]);returned=sum(r[i] for r in matrix)
            if support+returned:fs.append(2*matrix[i][i]/(support+returned))
        checks=[]
        for pid in recommended:
            policy=case.policies[pid]
            if not isinstance(policy.get('title',pid),str) or (policy.get('url') is not None and not isinstance(policy['url'],str)):
                raise ValueError('invalid policy display fields')
            constraints=case.policies[pid].get('constraint_checks')
            if constraints is None:continue
            if not isinstance(constraints,dict) or not all(isinstance(k,str) and v in ('pass','fail','unknown') for k,v in constraints.items()):
                raise ValueError('invalid frozen constraint checks')
            checks.extend({'policy_id':pid,'condition':k,'state':v} for k,v in constraints.items())
        rows.append({'case_id':case.id,'neighborhood':case.neighborhood,'source':case.source,'methodology':case.methodology,
            'policy_as_of':case.policy_as_of,'state':'evaluated' if complete else 'partial' if truth else 'not_evaluated',
            'output_status':output.status if output else 'missing_prediction','candidate_count':len(case.policies),'judged_count':len(truth),
            'reference_coverage':ratio(len(truth),len(case.policies)),'suitability_macro_f1':mean(fs) if fs else None,
            'suitability_class_policy':'classes_with_reference_or_prediction_support',
            'suitability_confusion':matrix,'suitability_classes':classes+['unknown_or_missing'],
            'retrieved_count':len(retrieved),'relevant_count':len(relevant),
            'retrieval_recall':ratio(len(set(retrieved)&relevant),len(relevant)),
            'cutoff':cutoff,f'recommendation_recall_at_{cutoff}':ratio(len(set(recommended)&relevant),len(relevant)),
            f'recall_at_{cutoff}_ceiling':ratio(min(cutoff,len(relevant)),len(relevant)),
            'precision':ratio(suitable,len(recommended)) if not unknown_returned else None,
            'precision_bounds':[ratio(suitable,len(recommended)),ratio(suitable+len(unknown_returned),len(recommended))],
            'conditional_rate':ratio(conditional,len(recommended)) if not unknown_returned else None,
            f'ndcg_at_{cutoff}':ndcg,'recommended_count':len(recommended),'unknown_returned':unknown_returned,
            'correct_hold':not recommended if complete and not relevant and not any(v=='conditional' for v in truth.values()) and output and output.status=='completed' else None,
            'constraint_violations':sum(c['state']=='fail' for c in checks) if checks else None,
            'constraint_unchecked_resources':sum(not case.policies[pid].get('constraint_checks') for pid in recommended),
            'constraint_checked':sum(c['state']!='unknown' for c in checks),'constraint_unknown':sum(c['state']=='unknown' for c in checks),
            'constraint_basis':'recorded_frozen_checks_not_live_eligibility',
            'retrieval_misses':sorted(relevant-set(retrieved)),'ranking_misses':sorted(relevant&set(retrieved)-set(recommended)),
            'recommendations':[{'id':pid,'reference':truth.get(pid,'unknown'),'title':case.policies[pid].get('title',pid),
                'url':case.policies[pid].get('url')} for pid in recommended]})
    return {'rows':rows,'limitations':['재현율은 고정 후보 중 독립 평정된 적합 정책을 분모로 사용합니다. 전체 정책을 모두 발견했다는 의미가 아닙니다.',
        '필수조건은 입력에 고정된 검사 기록이며 현재 자격·접수·정원을 확인한 값이 아닙니다.',
        'NDCG는 후보 하나라도 독립 평정이 없으면 미평가입니다. 적합성 예측 보류는 해당 참조 등급의 재현율을 낮춥니다.']}
