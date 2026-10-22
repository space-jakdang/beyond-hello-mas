"""Blind review packets and case-paired aggregation; missing ratings stay missing."""
import argparse
import json
import hashlib
from pathlib import Path
import random
from statistics import mean
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from backend.tools.indicators import digest
from eval.run_comparison import load_cases

MajorError = Literal['fabricated_evidence','group_to_person_claim','unverified_eligibility','approval_bypass']


class Reviewer(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(min_length=1)
    expertise:str=Field(min_length=1)
    development_participant:bool


class Rating(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    blind_id:str
    reviewer:str
    executable:bool
    major_errors:list[MajorError]
    reason:str=Field(min_length=1)
    supported_claims:int=Field(ge=0)
    reviewed_claims:int=Field(ge=0)
    omitted_constraints:bool
    appropriate_hold:bool | None
    excessive_hold:bool
    edits:int | None=Field(ge=0)
    task_seconds:float | None=Field(ge=0,allow_inf_nan=False)


class Adjudication(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    blind_id:str
    reviewer:str
    executable:bool
    major_errors:list[MajorError]
    reason:str=Field(min_length=1)
    appropriate_hold:bool | None
    excessive_hold:bool


class Ratings(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    reviewers:list[Reviewer]
    ratings:list[Rating]
    adjudications:list[Adjudication]=Field(default_factory=list)


def validate_report(report):
    if report.get('rating_code_hash')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('rating code changed; use the recorded code commit')
    contract,cases=load_cases(report['split'])
    if report['contract_hash']!=digest(contract) or report['contract']!=contract or report['input_hash']!=contract['files'][report['split']+'_inputs.json'] or report['label_hash']!=contract['files'][report['split']+'_labels.json']:
        raise ValueError('report contract mismatch')
    repetitions=report['repetitions']
    if type(repetitions) is not int or repetitions not in (1,contract['planned_live_repetitions']):raise ValueError('invalid repetitions')
    if report['mode']=='live' and repetitions!=contract['planned_live_repetitions']:raise ValueError('incomplete live repetitions')
    methods=report['methods_run']
    if len(set(methods))!=len(methods) or not set(methods)<=set(contract['methods']):raise ValueError('invalid methods')
    expected={(c['id'],rep,m) for c in cases for rep in range(1,repetitions+1) for m in methods}
    actual=[(r['case_id'],r['repetition'],r['method']) for r in report['results']]
    if set(actual)!=expected or len(actual)!=len(expected) or report['case_count']!=len(cases):raise ValueError('missing or duplicate paired cases')
    return {c['id']:c for c in cases}


def packet(report):
    cases=validate_report(report)
    items=[];key={}
    order=list(enumerate(report['results']));random.Random(20261020).shuffle(order)
    for index,row in order:
        blind_id=str(uuid4());key[blind_id]=index
        output=row['output'];plan=output.get('plan')
        reason=output.get('reason')
        if output['status'] in ('failed','not_executed') or output.get('failure_kind'):
            reason='실행이 완료되지 않아 담당자 확인이 필요합니다.'
        else:
            reason={'no_classified_cohorts':'판정 가능한 관측이 없습니다.',
                    'no_observations':'판정 가능한 관측이 없습니다.',
                    'evidence_unavailable':'요청한 관측 근거를 확인할 수 없습니다.'}.get(reason,reason)
        items.append({'blind_id':blind_id,'case_id':row['case_id'],
            'observations':cases[row['case_id']]['observations'],'allowed_evidence':cases[row['case_id']]['snapshots'],
            'output':{'status':'proposal' if plan else 'human_check','plan':plan,'reason':reason}})
    return {'report_hash':digest(report),'items':items,'limitations':['Method labels removed; wording may reveal method identity.']}, {'report_hash':digest(report),'mapping':key}


def aggregate(report,key,data):
    validate_report(report)
    data=Ratings.model_validate(data)
    if key['report_hash']!=digest(report):raise ValueError('report changed after blinding')
    if set(key['mapping'].values())!=set(range(len(report['results']))) or len(key['mapping'])!=len(report['results']):
        raise ValueError('invalid blinding map')
    reviewers={r.id:r for r in data.reviewers}
    if len(reviewers)!=len(data.reviewers):raise ValueError('duplicate reviewer')
    scores={};seen=set()
    for rating in data.ratings:
        if rating.blind_id not in key['mapping'] or rating.reviewer not in reviewers:raise ValueError('unknown rating ID')
        pair=(rating.blind_id,rating.reviewer)
        if pair in seen:raise ValueError('duplicate rating')
        seen.add(pair)
        if rating.supported_claims>rating.reviewed_claims:raise ValueError('supported exceeds reviewed claims')
        if len(set(rating.major_errors))!=len(rating.major_errors):raise ValueError('duplicate major error')
        scores.setdefault(rating.blind_id,[]).append(rating)
    adjudications={a.blind_id:a for a in data.adjudications}
    if len(adjudications)!=len(data.adjudications):raise ValueError('duplicate adjudication')
    if any(a.blind_id not in key['mapping'] or a.reviewer not in reviewers for a in data.adjudications):raise ValueError('unknown adjudication ID')
    outcomes={};missing=[];disagreements=[];not_independent=set()
    for blind_id,index in key['mapping'].items():
        ratings=scores.get(blind_id,[])
        if len(ratings)<2:missing.append(blind_id);continue
        if sum(not reviewers[r.reviewer].development_participant for r in ratings)<2:not_independent.add(blind_id)
        different=len({(r.executable,tuple(sorted(r.major_errors)),r.appropriate_hold,r.excessive_hold) for r in ratings})>1
        if different:disagreements.append(blind_id)
        adjudication=adjudications.get(blind_id)
        if adjudication and adjudication.reviewer in {r.reviewer for r in ratings}:raise ValueError('adjudicator must differ from original raters')
        if adjudication and not different:raise ValueError('adjudication requires disagreement')
        if adjudication and reviewers[adjudication.reviewer].development_participant:not_independent.add(blind_id)
        if different and adjudication is None:continue
        chosen=adjudication or ratings[0]
        row=report['results'][index]
        machine_failure=row['output']['status'] in ('failed','not_executed') or (row['output']['status']=='needs_human'
            and ('failure_kind' not in row['output'] or row['output']['failure_kind'] is not None))
        outcomes[index]={'success':chosen.executable and not chosen.major_errors and not machine_failure and not chosen.excessive_hold
                         and (row['output']['status']!='needs_human' or chosen.appropriate_hold is True),
                         'major':bool(chosen.major_errors)}
    complete=len(outcomes)==len(report['results'])
    metrics={};paired={}
    if complete:
        for method in report['methods_run']:
            indices=[i for i,r in enumerate(report['results']) if r['method']==method]
            metrics[method]={'successful_case_equivalents':sum(outcomes[i]['success'] for i in indices)/report['repetitions'],
                             'case_denominator':report['case_count'],'major_error_runs':sum(outcomes[i]['major'] for i in indices)}
        if 'collaboration' in metrics:
            for baseline in ('deterministic','single'):
                if baseline not in metrics:continue
                deltas=[]
                for case in sorted({r['case_id'] for r in report['results']}):
                    values={m:mean(outcomes[i]['success'] for i,r in enumerate(report['results']) if r['case_id']==case and r['method']==m)
                            for m in ('collaboration',baseline)}
                    deltas.append(values['collaboration']-values[baseline])
                rng=random.Random(20261020)
                bootstrap=sorted(mean(rng.choices(deltas,k=len(deltas))) for _ in range(2000))
                paired[baseline]={'wins':sum(v>0 for v in deltas),'ties':sum(v==0 for v in deltas),'losses':sum(v<0 for v in deltas),
                    'mean_difference':mean(deltas),'case_bootstrap_95_interval':[bootstrap[49],bootstrap[1949]],
                    'independent_cases':len(deltas)}
    contract=report['contract'];limits=all(r['cost_usd'] is not None and r['latency_seconds'] is not None and r['latency_seconds']<=contract['completion_deadline_seconds']
        and r['calls']<=contract['max_calls_per_method'] and r['reserved_usd']<=contract['max_cost_usd_per_run'] for r in report['results'])
    returned_models={model for row in report['results'] for model in row.get('returned_models',[])}
    eligible=len(returned_models)==1 and complete and not report['code_dirty'] and not not_independent and report['mode']=='live' and report['split']=='test' and report['status']=='awaiting_human_ratings' and len(metrics)==3
    if not eligible:decision='not_evaluated'
    else:
        gain=contract['adoption']['additional_successful_cases_vs_each_baseline']
        decision='candidate' if limits and metrics['collaboration']['major_error_runs']==0 and all(
            metrics['collaboration']['successful_case_equivalents']-metrics[b]['successful_case_equivalents']>=gain for b in ('deterministic','single')) else 'keep_existing_default'
    return {'report_hash':digest(report),'ratings_hash':digest(data.model_dump()),'missing':missing,'disagreements':disagreements,
        'unresolved_disagreements':[i for i in disagreements if i not in adjudications], 'not_independent':sorted(not_independent),
        'metrics':metrics if complete else None,'paired':paired if complete else None,'adoption_decision':decision,
        'within_limits':limits,'raw_ratings':data.model_dump(),
        'limitations':['Small balanced synthetic challenge set; intervals do not estimate field prevalence.',
                       'Task time and edits are recorded observations, not a randomized operator pilot.',
                       'Fake ratings cannot establish model quality or authorize adoption.']}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('report',type=Path);parser.add_argument('--ratings',type=Path);parser.add_argument('--key',type=Path)
    args=parser.parse_args();report=json.loads(args.report.read_text());folder=args.report.parent/('review-'+str(uuid4()));folder.mkdir()
    if args.ratings:
        if not args.key:parser.error('--ratings requires --key')
        result=aggregate(report,json.loads(args.key.read_text()),json.loads(args.ratings.read_text()))
        (folder/'ratings-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    else:
        public,key=packet(report)
        for name,value in [('packet',public),('private-key',key),('ratings-template',{'reviewers':[],'ratings':[],'adjudications':[]})]:
            (folder/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(folder)


if __name__=='__main__':main()
