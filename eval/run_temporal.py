"""Rolling origin: Jan–Jun warmup, Jul–Dec one-month holdout. No LLM or real data."""
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime,timezone
from uuid import uuid4
from backend.app.config import ROOT
from backend.tools.forecast import predict
from backend.tools.indicators import digest
from scripts.generate_temporal import generate,MONTHS,TEST_SEEDS


def metrics(rows):
    available = [r for r in rows if r['prediction'] is not None]
    tp = sum(r['prediction'] >= .7 and r['truth'] >= .7 for r in available)
    fp = sum(r['prediction'] >= .7 and r['truth'] < .7 for r in available)
    # Missing forecasts are not removed from the positive-event denominator.
    positives = sum(r['truth'] >= .7 for r in rows)
    return {'count':len(rows),'predicted':len(available),'coverage':len(available)/len(rows) if rows else None,
            'mae':sum(abs(r['prediction']-r['truth']) for r in available)/len(available) if available else None,
            'alert_precision':tp/(tp+fp) if tp+fp else None,'alert_recall':tp/positives if positives else None,
            'true_positives':tp,'false_positives':fp,'positive_events':positives}


def evaluate(seeds=TEST_SEEDS):
    results=[]; inputs={}; labels={}
    for seed in seeds:
        source=generate(seed)
        inputs[str(seed)]=digest([{k:r[k] for k in ('cohort','month','value')} for r in source])
        labels[str(seed)]=digest([{k:r[k] for k in ('cohort','month','truth','pattern')} for r in source])
        cohorts=defaultdict(list)
        for row in source: cohorts[row['cohort']].append(row)
        for cohort, series in cohorts.items():
            for target in series[6:]:
                # Only observed past values cross the predictor boundary, never labels or patterns.
                history=[{'month':r['month'],'value':r['value']} for r in series if r['month']<target['month']]
                for method in ('last_value','trend'):
                    results.append({'seed':seed,'cohort':cohort,'month':target['month'],'pattern':target['pattern'],
                                    'method':method,'prediction':predict(history,target['month'],method),'truth':target['truth']})
    by_month=[{'seed':seed,'month':month,'method':method,**metrics([r for r in results if r['seed']==seed and r['month']==month and r['method']==method])}
              for seed in seeds for month in MONTHS[6:] for method in ('last_value','trend')]
    overall={method:metrics([r for r in results if r['method']==method]) for method in ('last_value','trend')}
    by_pattern={pattern:{method:metrics([r for r in results if r['pattern']==pattern and r['method']==method]) for method in overall}
                for pattern in sorted({r['pattern'] for r in results})}
    return {'input_hashes':inputs,'label_hashes':labels,'result_hash':digest(results),'overall':overall,'by_month':by_month,'by_pattern':by_pattern}


def run():
    first=evaluate();second=evaluate();id=str(uuid4())
    files=['backend/tools/forecast.py','scripts/generate_temporal.py','eval/run_temporal.py']
    report={'schema_version':'3','id':id,'created_at':datetime.now(timezone.utc).isoformat(),'data_mode':'sample','llm_mode':'fake',
        'status':'executed_synthetic_forecast','evaluated_scenarios':first['overall']['trend']['count'],
        'metrics':first['overall'],'temporal':{'by_month':first['by_month'],'by_pattern':first['by_pattern']},
        'results':[],'uncompleted':[], 'stage_reproducibility':{'repetitions':2,'scope':'same process, same code and seeds','identical':first==second},
        'metadata':{'suite':'synthetic-temporal-1','input_hashes':first['input_hashes'],'label_hashes':first['label_hashes'],'scenario_count_basis':'cohort/target-month/seed cases per method; two methods share cases','result_hash':first['result_hash'],
            'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'code_hash':digest({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}),
            'code_dirty':bool(subprocess.check_output(['git','status','--porcelain','--',*files],cwd=ROOT,text=True).strip()),
            'warmup_months':MONTHS[:6],'test_months':MONTHS[6:],'test_seeds':list(TEST_SEEDS),'horizon_months':1,
            'threshold':.7,'threshold_basis':'synthetic stress-test threshold, not clinical','cost_usd':0},
        'limitations':['인공적으로 생성한 지역 신호의 예측이며 실제 고립 발생 예측 정확도가 아닙니다.',
            '직전 관측 유지와 최근 3개 관측 선형 추세를 비교하며 학습한 예측 모델이 아닙니다.',
            '매월 그 이전 관측만 사용합니다. 이전 시험 월은 이후 월의 과거 관측으로 사용할 수 있습니다.',
            'MAE는 예측 가능한 건만 계산하며 coverage를 병기합니다. 미예측 양성은 recall 분모에 남습니다.',
            '합성 시계열은 전달받은 월 없는 실제 집계를 복제하거나 보정한 것이 아닙니다.',
            '잠재 신호와 잡음이 있는 관측을 분리합니다. 정답은 잠재 신호이며 모델에는 과거 관측만 전달합니다.',
            '재현성은 동일 프로세스에서 같은 코드·seed로 2회 실행한 검사입니다.']}
    folder=ROOT/'eval/reports'/datetime.now(timezone.utc).strftime('%Y%m%d')/id
    folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'report':str(folder.relative_to(ROOT)),'identical':first==second,'metrics':first['overall']},ensure_ascii=False))
    return report


if __name__=='__main__':
    if not run()['stage_reproducibility']['identical']: raise SystemExit(2)
