"""Independent rubric review is separate from source validation and execution success."""
import json
from datetime import date
from statistics import mean
from typing import Literal
from pydantic import Field
from eval.quality_contracts import Contract,Reviewer,load_frozen
from backend.policy.design_contracts import validate_draft
from backend.tools.indicators import digest

AXES=('grounding','feasibility','clarity','equity','evaluation_plan')


class DraftCase(Contract):
    case_id:str
    run_id:str|None=None
    document:dict


class DraftInputs(Contract):
    dataset_hash:str
    cases:list[DraftCase]


class Rating(Contract):
    case_id:str
    version:str
    reviewer:str
    reviewed_at:str
    scores:dict[Literal['grounding','feasibility','clarity','equity','evaluation_plan'],int|None]
    reason:str=Field(min_length=1)


class Ratings(Contract):
    input_hash:str
    reviewers:list[Reviewer]
    ratings:list[Rating]


def quality(frozen,inputs,ratings=None,case_ids=None):
    dataset=load_frozen(frozen);inputs=DraftInputs.model_validate(inputs)
    if inputs.dataset_hash!=frozen['dataset_hash']:raise ValueError('draft dataset mismatch')
    cases={c.id:c for c in dataset.cases};docs={c.case_id:c for c in inputs.cases}
    if len(docs)!=len(inputs.cases) or not set(docs)<=set(cases):raise ValueError('unknown or duplicate draft case')
    input_hash=digest(inputs.model_dump());rated=Ratings.model_validate(ratings or {'input_hash':input_hash,'reviewers':[],'ratings':[]})
    if rated.input_hash!=input_hash:raise ValueError('ratings refer to another draft version')
    reviewers={r.id:r for r in rated.reviewers}
    if len(reviewers)!=len(rated.reviewers):raise ValueError('duplicate reviewer')
    grouped={};seen=set()
    for rating in rated.ratings:
        date.fromisoformat(rating.reviewed_at)
        if rating.case_id not in docs or rating.reviewer not in reviewers or rating.version!=docs[rating.case_id].document.get('version'):
            raise ValueError('unknown rating case/reviewer/version')
        if set(rating.scores)!=set(AXES) or any(v is not None and (type(v) is not int or not 1<=v<=5) for v in rating.scores.values()):
            raise ValueError('rubric needs five axes rated1..5 or unknown')
        key=(rating.case_id,rating.reviewer)
        if key in seen:raise ValueError('duplicate rating')
        seen.add(key);grouped.setdefault(rating.case_id,[]).append(rating)
    rows=[]
    for case_id,item in docs.items():
        if case_ids is not None and case_id not in case_ids:continue
        doc=item.document;draft=doc.get('draft');valid=None
        if draft:
            checked=validate_draft(draft,doc.get('considered_evidence_ids') or draft['problem_evidence_ids'],doc['gap'],doc['analogues'])
            if checked['version']!=doc.get('version'):raise ValueError('draft provenance version changed')
            valid=True
        independent=[r for r in grouped.get(case_id,[]) if not reviewers[r.reviewer].development_participant]
        metrics={}
        for axis in AXES:
            values=[r.scores[axis] for r in independent if r.scores[axis] is not None]
            metrics[axis]={'state':'disagreement' if len(values)>=2 and max(values)-min(values)>=2 else 'evaluated' if len(values)>=2 else 'not_evaluated',
                'mean':mean(values) if len(values)>=2 and max(values)-min(values)<2 else None,'range':[min(values),max(values)] if values else None,'independent_count':len(values)}
        rows.append({'case_id':case_id,'neighborhood':cases[case_id].neighborhood,'source':cases[case_id].source,'version':doc.get('version'),
            'run_id':item.run_id,'draft_status':doc['status'],'source_validation':valid,'independent_reviews':len(independent),
            'rubric':metrics,'field_effectiveness':None})
    return {'input_hash':input_hash,'rows':rows,'limitations':['첨부된 원문과의 대조 성공은 정책 효과·실현 가능성을 입증하지 않습니다.',
        '각 축 1–5점 독립 평정이 2명 미만이면 미평가입니다. 2점 이상 차이는 불일치로 표시하며 평균을 제시하지 않습니다.']}


def load(folder,frozen,case_ids):
    path=folder/'policy-drafts.json';rating_path=folder/'policy-draft-ratings.json'
    if not path.exists() and not path.is_symlink():
        if rating_path.exists():raise ValueError('ratings without draft inputs')
        return None
    if path.is_symlink() or rating_path.is_symlink():raise ValueError('symlink not allowed')
    return quality(frozen,json.loads(path.read_text()),json.loads(rating_path.read_text()) if rating_path.exists() else None,case_ids)
