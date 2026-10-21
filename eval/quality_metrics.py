"""Quality metrics from frozen reference labels; no labels or predictions invented."""
from typing import Literal
from pydantic import Field, model_validator
from eval.quality_contracts import Contract, load_frozen, resolve_labels
from backend.tools.indicators import digest


class Prediction(Contract):
    case_id: str = Field(min_length=1)
    grade: int | None = Field(default=None, ge=1, le=5)
    status: Literal['predicted','abstained','failed']
    run_id: str | None = None

    @model_validator(mode='after')
    def consistent(self):
        if (self.status == 'predicted') != (self.grade is not None):
            raise ValueError('grade and prediction status disagree')
        return self


class Predictions(Contract):
    dataset_hash: str
    version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    method: Literal['rules','single','mas']
    predictions: list[Prediction]


def validate_predictions(frozen, body):
    dataset=load_frozen(frozen)
    data=Predictions.model_validate(body)
    if data.dataset_hash != frozen['dataset_hash']:
        raise ValueError('prediction dataset hash mismatch')
    ids=[p.case_id for p in data.predictions]
    if len(ids)!=len(set(ids)) or not set(ids)<={c.id for c in dataset.cases}:
        raise ValueError('unknown or duplicate prediction case')
    return data


def ratio(n,d):
    return n/d if d else None


def classification(frozen, labels, predictions, case_ids=None):
    dataset=load_frozen(frozen); data=validate_predictions(frozen,predictions)
    references=resolve_labels(frozen,labels)['references']
    refs={r['case_id']:r for r in references if r['policy_id'] is None}
    predicted={p.case_id:p for p in data.predictions}
    groups={}
    for case in dataset.cases:
        if case_ids is not None and case.id not in case_ids:continue
        group=groups.setdefault((case.source,case.methodology),[])
        group.append(case)
    result=[]
    for (source,methodology),cases in groups.items():
        matrix=[[0]*6 for _ in range(5)];errors=[];pairs=[];missing_labels=unknown_labels=non_independent=0
        for case in cases:
            reference=refs[case.id]
            if reference['state']=='unknown':unknown_labels+=1;continue
            if reference['state']!='resolved':missing_labels+=1;continue
            if not reference['independent']:non_independent+=1;continue
            truth=int(reference['value']);p=predicted.get(case.id);grade=p.grade if p else None
            matrix[truth-1][grade-1 if grade is not None else 5]+=1
            pairs.append((truth,grade))
            if grade!=truth:errors.append({'case_id':case.id,'neighborhood':case.neighborhood,'reference':truth,
                'predicted':grade,'status':p.status if p else 'missing_prediction','run_id':p.run_id if p else None})
        n=len(pairs);valid=sum(g is not None for _,g in pairs);per_grade=[];fs=[]
        for i in range(5):
            support=sum(matrix[i]);returned=sum(row[i] for row in matrix);tp=matrix[i][i]
            f1=ratio(2*tp,support+returned)
            if support+returned:fs.append(f1)
            per_grade.append({'grade':i+1,'support':support,'predicted_count':returned,
                'precision':ratio(tp,returned),'recall':ratio(tp,support),'f1':f1})
        positive=sum(t>=4 for t,_ in pairs);flagged=sum(g is not None and g>=4 for _,g in pairs)
        hit=sum(t>=4 and g is not None and g>=4 for t,g in pairs)
        result.append({'source':source,'methodology':methodology,'state':'evaluated' if n else 'not_evaluated',
            'input_cases':len(cases),'reference_count':n,'missing_labels':missing_labels,'unknown_labels':unknown_labels,
            'non_independent_labels':non_independent,'valid_predictions':valid,'missing_predictions':n-valid,
            'macro_f1':sum(fs)/len(fs) if fs else None,'macro_class_policy':'grades_with_reference_or_prediction_support',
            'priority_precision':ratio(hit,flagged),'priority_recall':ratio(hit,positive),'priority_support':positive,
            'priority_flagged':flagged,'flag_rate':ratio(flagged,n),'coverage':ratio(valid,n),
            'mae':ratio(sum(abs(t-g) for t,g in pairs if g is not None),valid),
            'confusion':matrix,'per_grade':per_grade,'errors':errors})
    return {'prediction_hash':digest(data.model_dump()),'model':data.model,'method':data.method,
            'version':data.version,'groups':result}
