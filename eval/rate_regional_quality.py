"""Bind the existing independent output rubric to recorded regional-quality runs."""
import argparse
import json
from pathlib import Path
import random
from statistics import mean
from uuid import uuid4
from pydantic import Field
from backend.tools.indicators import digest
from eval.rate_comparison import Ratings,Adjudication
from eval.run_regional_quality import validate_report,METHODS


class OutputAdjudication(Adjudication):
    omitted_constraints:bool


class OutputRatings(Ratings):
    adjudications:list[OutputAdjudication]=Field(default_factory=list)


def packet(frozen,report):
    cases=validate_report(frozen,report);items=[];mapping={}
    for record in report['records']:
        for cid in record['case_ids']:
            case=cases[cid];identifier=str(uuid4());proposal=record['proposal']
            row=next((r for r in proposal['assignments'] if r['evidence_id']==case.facts['evidence_id']),None) if proposal else None
            output={'status':'failed'} if not proposal else {'status':proposal['workflow']['status'],
                'analysis':proposal['workflow'].get('analysis'),'statistics_status':proposal['workflow']['statistics']['status'],'candidate_status':row['status'],
                'needs':row['need_profile'],'candidates':row['recommendations'],'policy_gap':row.get('policy_gap')}
            items.append({'blind_id':identifier,'facts':case.facts,'policies':case.policies,'output':output})
            mapping[identifier]={'case_id':cid,'method':record['method'],'run_id':record['run_id']}
    random.SystemRandom().shuffle(items)
    common={'dataset_hash':frozen['dataset_hash'],'report_hash':digest(report)}
    return {**common,'items':items,'limitations':['Method labels and run IDs removed; output wording can still reveal a method.',
        'Reviewed status permits candidate calculation; it does not establish independent semantic review.']},{**common,'mapping':mapping}


def aggregate(frozen,report,key,body,case_ids=None):
    cases=validate_report(frozen,report);data=OutputRatings.model_validate(body)
    expected={(r['method'],cid,r['run_id']) for r in report['records'] for cid in r['case_ids']}
    mapping=key['mapping'];actual=[(r['method'],r['case_id'],r['run_id']) for r in mapping.values()]
    if key['report_hash']!=digest(report) or key['dataset_hash']!=frozen['dataset_hash'] or len(actual)!=len(expected) or set(actual)!=expected:
        raise ValueError('blinding map or recorded output changed')
    reviewers={r.id:r for r in data.reviewers}
    if len(reviewers)!=len(data.reviewers):raise ValueError('duplicate reviewer')
    grouped={};seen=set()
    for rating in data.ratings:
        if rating.blind_id not in mapping or rating.reviewer not in reviewers:raise ValueError('unknown rating ID')
        pair=(rating.blind_id,rating.reviewer)
        if pair in seen:raise ValueError('duplicate rating')
        seen.add(pair)
        if rating.supported_claims>rating.reviewed_claims or len(set(rating.major_errors))!=len(rating.major_errors):raise ValueError('invalid claim or error counts')
        grouped.setdefault(rating.blind_id,[]).append(rating)
    adjudications={a.blind_id:a for a in data.adjudications}
    if len(adjudications)!=len(data.adjudications):raise ValueError('duplicate adjudication')
    for a in data.adjudications:
        if a.blind_id not in mapping or a.reviewer not in reviewers:raise ValueError('unknown adjudication')
    outcomes={};states={}
    fields=lambda r:(r.executable,tuple(sorted(r.major_errors)),r.omitted_constraints,r.appropriate_hold,r.excessive_hold)
    for identifier,link in mapping.items():
        ratings=grouped.get(identifier,[]);different=len({fields(r) for r in ratings})>1;adjudication=adjudications.get(identifier)
        if adjudication and (len(ratings)<2 or not different or adjudication.reviewer in {r.reviewer for r in ratings}):raise ValueError('invalid adjudicator or missing disagreement')
        independent=len(ratings)>=2 and not any(reviewers[r.reviewer].development_participant for r in ratings+[adjudication] if r)
        states[identifier]='missing' if len(ratings)<2 else 'not_independent' if not independent else 'disagreement' if different and not adjudication else 'resolved'
        if states[identifier]!='resolved':continue
        chosen=adjudication or ratings[0]
        record=next(r for r in report['records'] if r['run_id']==link['run_id']);proposal=record['proposal']
        failed=not proposal or any(p.get('error_type') or p.get('failure_kind') for p in (proposal['workflow'],proposal['workflow']['statistics'],proposal['workflow'].get('matching') or {}))
        assignment=next((r for r in proposal['assignments'] if r['evidence_id']==cases[link['case_id']].facts['evidence_id']),None) if proposal else None
        held=not proposal or proposal['workflow']['status']!='reviewed' or not assignment['recommendations']
        outcomes[identifier]={'success':not failed and chosen.executable and not chosen.major_errors and not chosen.omitted_constraints and not chosen.excessive_hold and (not held or chosen.appropriate_hold is True),
            'major':bool(chosen.major_errors),'omitted':chosen.omitted_constraints,'appropriate_hold':held and chosen.appropriate_hold is True,'excessive_hold':chosen.excessive_hold,
            'supported_claim_ratings':sum(r.supported_claims for r in ratings),'reviewed_claim_ratings':sum(r.reviewed_claims for r in ratings),
            'edits':mean(r.edits for r in ratings if r.edits is not None) if any(r.edits is not None for r in ratings) else None,
            'seconds':mean(r.task_seconds for r in ratings if r.task_seconds is not None) if any(r.task_seconds is not None for r in ratings) else None}
    selected={cid for cid in cases if case_ids is None or cid in case_ids};methods=[]
    for method in METHODS:
        ids=[identifier for identifier,link in mapping.items() if link['method']==method and link['case_id'] in selected]
        resolved=[identifier for identifier in ids if identifier in outcomes];families={}
        for identifier in resolved:families.setdefault(cases[mapping[identifier]['case_id']].family_id,[]).append(outcomes[identifier]['success'])
        methods.append({'method':method,'case_count':len(ids),'family_count':len({cases[mapping[i]['case_id']].family_id for i in ids}),
            'resolved':len(resolved),'missing':sum(states[i]=='missing' for i in ids),'disagreement':sum(states[i]=='disagreement' for i in ids),'not_independent':sum(states[i]=='not_independent' for i in ids),
            'success_rate':mean(outcomes[i]['success'] for i in resolved) if ids and len(resolved)==len(ids) else None,
            'family_success_rate':mean(mean(v) for v in families.values()) if ids and len(resolved)==len(ids) else None,
            'major_error_cases':sum(outcomes[i]['major'] for i in resolved),
            'omitted_constraint_cases':sum(outcomes[i]['omitted'] for i in resolved),'appropriate_hold_cases':sum(outcomes[i]['appropriate_hold'] for i in resolved),
            'excessive_hold_cases':sum(outcomes[i]['excessive_hold'] for i in resolved),
            'supported_claim_ratings':sum(outcomes[i]['supported_claim_ratings'] for i in resolved),'reviewed_claim_ratings':sum(outcomes[i]['reviewed_claim_ratings'] for i in resolved),
            'mean_edits':mean(outcomes[i]['edits'] for i in resolved if outcomes[i]['edits'] is not None) if any(outcomes[i]['edits'] is not None for i in resolved) else None,
            'mean_task_seconds':mean(outcomes[i]['seconds'] for i in resolved if outcomes[i]['seconds'] is not None) if any(outcomes[i]['seconds'] is not None for i in resolved) else None,
            'edit_observations':sum(outcomes[i]['edits'] is not None for i in resolved),'time_observations':sum(outcomes[i]['seconds'] is not None for i in resolved)})
    by_unit={(link['method'],link['case_id']):identifier for identifier,link in mapping.items()};paired=[]
    for baseline in ('rules','single'):
        families={};wins=losses=ties=0;count=0
        for cid in selected:
            first=outcomes.get(by_unit[(baseline,cid)]);second=outcomes.get(by_unit[('mas',cid)])
            if first is None or second is None:continue
            delta=int(second['success'])-int(first['success']);families.setdefault(cases[cid].family_id,[]).append(delta)
            count+=1;wins+=delta>0;losses+=delta<0;ties+=delta==0
        paired.append({'baseline':baseline,'challenger':'mas','case_count':len(selected),'paired_resolved':count,'family_count':len(families),
            'wins':wins,'ties':ties,'losses':losses,'family_success_delta':mean(mean(v) for v in families.values()) if selected and count==len(selected) else None})
    return {'version':'regional-output-ratings-1','report_hash':digest(report),'ratings_hash':digest(data.model_dump()),
        'mode':report['mode'],'methods':methods,'paired':paired,'evaluation_complete':False,'adoption_decision':'not_evaluated',
        'limitations':['계열·사례별 기술 통계입니다. 누락·이견·개발 참여 평정을 독립 합의로 바꾸지 않습니다.',
            '수정·소요 시간은 평정자가 기록한 관찰이며 무작위 담당자 실험이 아닙니다.',
            'fake 실행은 계약 검증입니다. 실제 정책 조사·설계 전체, 외부 전이·현장 효과는 이 비교에 포함하지 않습니다.',
            '사전 계획의 독립 사례·평정·유료 실행 관문은 별도이며 이 요약은 평가 완료나 채택 승인이 아닙니다.']}


def load(folder,frozen,case_ids):
    path=folder/'workflow-runs.json'
    if not path.exists() and not path.is_symlink():return None
    paths=[folder/(name+'.json') for name in ('workflow-runs','workflow-private-key','workflow-ratings')]
    if any(p.is_symlink() for p in paths):raise ValueError('workflow evaluation symlink not allowed')
    report=json.loads(path.read_text())
    prediction_path=folder/'predictions.json'
    if prediction_path.is_symlink():raise ValueError('prediction symlink not allowed')
    if prediction_path.exists():
        from eval.quality_metrics import validate_predictions
        predictions=validate_predictions(frozen,json.loads(prediction_path.read_text())).model_dump()
        if not any(validate_predictions(frozen,arm['predictions']).model_dump()==predictions for arm in report['arms']):raise ValueError('predictions differ from recorded workflow runs')
    if paths[1].exists() or paths[2].exists():
        key,data=[json.loads(p.read_text()) for p in paths[1:]]
    else:
        mapping={str(i):{'method':r['method'],'case_id':cid,'run_id':r['run_id']} for i,(r,cid) in enumerate((r,cid) for r in report['records'] for cid in r['case_ids'])}
        key={'dataset_hash':frozen['dataset_hash'],'report_hash':digest(report),'mapping':mapping};data={'reviewers':[],'ratings':[]}
    return aggregate(frozen,report,key,data,case_ids)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path);args=parser.parse_args()
    folder=args.folder;read=lambda name:json.loads((folder/(name+'.json')).read_text())
    public,key=packet(read('inputs'),read('workflow-runs'))
    for name,body in [('workflow-blind-packet',public),('workflow-private-key',key),('workflow-ratings',{'reviewers':[],'ratings':[],'adjudications':[]})]:
        path=folder/(name+'.json')
        with path.open('x') as file:file.write(json.dumps(body,ensure_ascii=False,indent=2)+'\n')
    print(folder)


if __name__=='__main__':main()
