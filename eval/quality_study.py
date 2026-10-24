"""Matched-method comparisons and explicitly declared transfer scopes."""
import argparse
import calendar
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from pydantic import Field, model_validator
from backend.tools.indicators import digest
from eval.quality_contracts import Contract, load_frozen, resolve_labels, stage_scope
from eval.quality_metrics import Predictions, classification, validate_predictions
from eval.quality_matching import matching


class Conditions(Contract):
    model: str = Field(min_length=1)
    tools_version: str = Field(min_length=1)
    catalog_hash: str = Field(min_length=1)
    max_calls: int = Field(ge=0)
    max_usd: float = Field(ge=0,allow_inf_nan=False)


class Timing(Contract):
    input_available_at: str
    predicted_at: str
    outcome_available_at: str

    @model_validator(mode='after')
    def ordered(self):
        values=[datetime.fromisoformat(getattr(self,k)) for k in ('input_available_at','predicted_at','outcome_available_at')]
        if any(v.tzinfo is None for v in values) or not values[0]<=values[1]<values[2]:
            raise ValueError('timing requires ordered timezone-aware timestamps')
        return self


class Telemetry(Contract):
    run_id: str
    cost_usd: float | None = Field(ge=0,allow_inf_nan=False)
    latency_seconds: float | None = Field(ge=0,allow_inf_nan=False)


class Arm(Contract):
    conditions: Conditions
    predictions: Predictions
    telemetry: list[Telemetry] = []


class Study(Contract):
    version: str = Field(min_length=1)
    dataset_hash: str
    label_hash: str
    development_regions: list[str]
    conditions: Conditions
    timing: dict[str,Timing] = {}
    arms: list[Arm] = Field(min_length=2,max_length=3)


def percentile(values,q):
    if not values:return None
    values=sorted(values);index=(len(values)-1)*q;low=int(index)
    return values[low]+(values[min(low+1,len(values)-1)]-values[low])*(index-low)


def compare_study(frozen,labels,body,case_ids=None):
    dataset=load_frozen(frozen);refs=resolve_labels(frozen,labels);study=Study.model_validate(body)
    if study.dataset_hash!=frozen['dataset_hash'] or study.label_hash!=refs['label_hash']:
        raise ValueError('study dataset or label version differs')
    cases={c.id:c for c in dataset.cases}
    if not set(study.timing)<=set(cases):raise ValueError('unknown timed case')
    methods=[a.predictions.method for a in study.arms]
    if len(set(methods))!=len(methods):raise ValueError('duplicate comparison method')
    if study.conditions.catalog_hash!=digest({c.id:c.policies for c in dataset.cases}):
        raise ValueError('catalog snapshot hash differs')
    used_runs=set()
    for arm in study.arms:
        validate_predictions(frozen,arm.predictions.model_dump())
        if arm.conditions!=study.conditions or (arm.predictions.method!='rules' and arm.predictions.model!=study.conditions.model):
            raise ValueError('comparison conditions differ')
        run_ids={p.run_id for p in arm.predictions.predictions if p.run_id}
        if used_runs & run_ids:raise ValueError('source run reused across comparison methods')
        used_runs.update(run_ids)
        telemetry_ids=[t.run_id for t in arm.telemetry]
        if len(set(telemetry_ids))!=len(telemetry_ids) or not set(telemetry_ids)<=run_ids:
            raise ValueError('duplicate or unknown telemetry run')
    for cid,timing in study.timing.items():
        case=cases[cid];year,month=map(int,case.period.split('-'))
        start=datetime(year,month,1,tzinfo=timezone.utc)
        end=datetime(year,month,calendar.monthrange(year,month)[1],23,59,59,tzinfo=timezone.utc)
        if datetime.fromisoformat(timing.predicted_at)>=start or datetime.fromisoformat(timing.outcome_available_at)<=end:
            raise ValueError('forecast must precede target month and outcome must follow it')
    selected=[c for c in dataset.cases if case_ids is None or c.id in case_ids]
    groups={}
    for case in selected:
        groups.setdefault((case.source,case.methodology,case.split,case.region,case.period,stage_scope(case)),[]).append(case)
    dev_regions=set(study.development_regions)|{c.region for c in dataset.cases if c.split!='test'}
    known_dev=('강남','춘천','gangnam','chuncheon')
    outputs=[]
    independent={r['case_id']:int(r['value']) for r in refs['references'] if r['policy_id'] is None and r['independent'] and r['state']=='resolved'}
    for (source,methodology,split,region,period,scale),members in groups.items():
        ids={c.id for c in members};arms=[];correct={};rankings={}
        for arm in study.arms:
            p=arm.predictions;by_id={r.case_id:r for r in p.predictions}
            score=classification(frozen,labels,p.model_dump(),ids)['groups'][0]
            resources=(matching(frozen,labels,p.model_dump(),ids) or {'rows':[]})['rows']
            correct[p.method]={c.id:int(c.id in by_id and by_id[c.id].grade==independent[c.id]) for c in members if c.id in independent}
            rankings[p.method]={r['case_id']:r['ndcg_at_3'] for r in resources}
            arms.append({'method':p.method,'model':p.model,'prediction_hash':digest(p.model_dump()),'classification':score,
                'matching':resources,'failed':sum(by_id[c.id].status=='failed' for c in members if c.id in by_id),
                'resource_failed':sum(by_id[c.id].resources is not None and by_id[c.id].resources.status=='failed' for c in members if c.id in by_id),
                'abstained':sum(by_id[c.id].status=='abstained' for c in members if c.id in by_id),
                'missing':sum(c.id not in by_id for c in members)})
        paired=[]
        for i,first in enumerate(methods):
            for second in methods[i+1:]:
                families={};ranking_families={};fixed=introduced=0
                for c in members:
                    if c.id in independent:
                        a,b=correct[first][c.id],correct[second][c.id]
                        families.setdefault(c.family_id,[]).append(b-a);fixed+=int(b>a);introduced+=int(a>b)
                    a,b=rankings[first].get(c.id),rankings[second].get(c.id)
                    if a is not None and b is not None:ranking_families.setdefault(c.family_id,[]).append(b-a)
                delta=mean(mean(v) for v in families.values()) if families else None
                paired.append({'baseline':first,'challenger':second,'family_count':len(families),'grade_accuracy_delta':delta,
                    'corrected_cases':fixed,'introduced_errors':introduced,'ranking_family_count':len(ranking_families),
                    'ndcg_delta':mean(mean(v) for v in ranking_families.values()) if ranking_families else None,
                    'conclusion':'descriptive_improvement' if delta is not None and delta>0 else 'improvement_not_established',
                    'confidence_interval':None})
        external=bool(study.development_regions) and source=='observed' and split=='test' and region not in dev_regions and not any(k in region.lower() for k in known_dev)
        temporal=source=='observed' and split=='test' and all(c.id in study.timing for c in members)
        outputs.append({'source':source,'methodology':methodology,'stage_scale':scale,'split':split,'region':region,'period':period,
            'case_count':len(members),'timed_cases':sum(c.id in study.timing for c in members),'family_count':len({c.family_id for c in members}),
            'transfer_scope':'declared_external_test' if external else 'synthetic_robustness' if source=='synthetic' else 'development_history_unconfirmed' if source=='observed' and split=='test' and not study.development_regions and region not in dev_regions and not any(k in region.lower() for k in known_dev) else 'development_revalidation',
            'temporal_scope':'declared_prospective_test' if temporal else 'not_evaluated',
            'arms':arms,'paired':paired})
    costs=[]
    for arm in study.arms:
        latencies=[t.latency_seconds for t in arm.telemetry if t.latency_seconds is not None]
        run_ids={p.run_id for p in arm.predictions.predictions if p.run_id}
        costs.append({'method':arm.predictions.method,'run_count':len(run_ids),'recorded_runs':len(arm.telemetry),'unlinked_predictions':sum(p.run_id is None for p in arm.predictions.predictions),
            'known_cost_usd':sum(t.cost_usd for t in arm.telemetry if t.cost_usd is not None),
            'unknown_cost_runs':len(run_ids)-sum(t.cost_usd is not None for t in arm.telemetry),
            'p50_seconds':percentile(latencies,.5),'p95_seconds':percentile(latencies,.95),'latency_runs':len(latencies)})
    return {'version':study.version,'protocol_hash':digest(study.model_dump()),'groups':outputs,'costs':costs,
        'cost_scope':'whole_study_before_filters','telemetry_provenance':'imported_not_ledger_verified',
        'limitations':['동일 조건은 등록된 프로토콜 기준이며 실제 실행 준수 여부의 독립 감사가 아닙니다.',
            '개발 지역·시점 기록의 완전성은 자료 제공자의 확인이 필요합니다. 강남·춘천은 개발 재검증입니다.',
            '원천 계열 내 차이를 평균한 후 계열별 동일 가중치를 적용합니다. 사례 수를 독립 표본 수로 취급하지 않습니다.',
            '차이는 기술 통계입니다. 통계적 유의성·신뢰구간·현장 개선 효과를 주장하지 않습니다.',
            '비용과 지연은 가져온 실행별 기록이며 미기록은 무료 또는 0초를 뜻하지 않습니다.']}


def load_study(folder,frozen,labels,case_ids):
    path=folder/'study.json'
    if not path.exists() and not path.is_symlink():return None
    if path.is_symlink():raise ValueError('study symlink not allowed')
    return compare_study(frozen,labels,json.loads(path.read_text()),case_ids)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path);args=parser.parse_args()
    read=lambda name:json.loads((args.folder/name).read_text())
    print(json.dumps(compare_study(read('inputs.json'),read('labels.json'),read('study.json')),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
