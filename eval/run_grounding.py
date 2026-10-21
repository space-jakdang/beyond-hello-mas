"""Evaluate recorded model context/output pairs; no retrospective evidence augmentation."""
import argparse
import asyncio
import json
import math
from pathlib import Path
from uuid import UUID
from backend.app.config import Settings
from backend.events import EventStore
from backend.tools.indicators import digest
from eval.quality_contracts import load_frozen
from eval.quality_metrics import validate_predictions


async def evaluate(folder, store, settings, other_ledgers, references=None, roles=None):
    from eval.ragas_judge import BudgetedJudge
    from ragas import SingleTurnSample
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall
    frozen=json.loads((folder/'inputs.json').read_text());dataset=load_frozen(frozen)
    predictions=validate_predictions(frozen,json.loads((folder/'predictions.json').read_text()))
    reference_texts=references or {}
    roles=roles or ['workflow_analyst','workflow_matching','policy_decision']
    if not set(roles)<={'workflow_analyst','workflow_matching','policy_decision'}:raise ValueError('invalid source role')
    if not set(reference_texts)<={c.id for c in dataset.cases} or any(not isinstance(t,str) or not t.strip() for t in reference_texts.values()):
        raise ValueError('invalid grounding reference cases')
    sources=[]
    for row in predictions.predictions:
        if row.run_id is None:continue
        UUID(row.run_id)
        with store.connection() as db:
            calls=db.execute("SELECT call_key,body FROM llm_calls WHERE run_id=? AND status='ok' AND role IN ('workflow_analyst','workflow_matching','policy_decision') ORDER BY rowid",(row.run_id,)).fetchall()
        for call in calls:
            body=json.loads(call['body'])
            if body.get('role') not in roles:continue
            if body.get('mode')!='live' or 'input' not in body or 'output' not in body:continue
            if body['role']=='policy_decision' and body['output'].get('action')!='finish':continue
            sources.append((row.case_id,row.run_id,call['call_key'],body))
    if not sources:raise ValueError('no recorded live model contexts for imported predictions')
    judge=BudgetedJudge(store,settings,other_ledgers)
    rows=[]
    try:
        for case_id,source_run,call_key,body in sources:
            sample=SingleTurnSample(user_input=body['prompt'],response=json.dumps(body['output'],ensure_ascii=False),
                retrieved_contexts=[json.dumps(body['input'],ensure_ascii=False)],reference=reference_texts.get(case_id))
            metrics={'faithfulness':Faithfulness(llm=judge)}
            if sample.reference:
                metrics.update(context_precision=LLMContextPrecisionWithReference(llm=judge),context_recall=LLMContextRecall(llm=judge))
            values={}
            for name,metric in metrics.items():
                try:
                    value=float(await metric.single_turn_ascore(sample))
                    values[name]={'value':value if math.isfinite(value) else None,'state':'evaluated' if math.isfinite(value) else 'not_evaluated'}
                except Exception as exc:
                    values[name]={'value':None,'state':'failed','error_type':type(exc).__name__}
            for name in ('context_precision','context_recall'):
                values.setdefault(name,{'value':None,'state':'not_evaluated','reason':'reference_text_missing'})
            rows.append({'case_id':case_id,'source_run_id':source_run,'source_call_key':call_key,'source_hash':digest(body),
                'role':body['role'],'metrics':values})
        failed=any(m['state']=='failed' for r in rows for m in r['metrics'].values())
        judge.finish(failed)
    except BaseException:
        judge.finish(True);raise
    with store.connection() as db:
        calls=[dict(r) for r in db.execute('SELECT status,reserve_usd,body FROM llm_calls WHERE run_id=?',(judge.run_id,))]
    return {'schema_version':'6','dataset_hash':frozen['dataset_hash'],'prediction_hash':digest(predictions.model_dump()),
        'reference_hash':digest(reference_texts),'references':reference_texts,'judge_run_id':judge.run_id,'judge_model':settings.openai_model,'ragas_version':'0.4.3',
        'state':'partial' if failed else 'evaluated','rows':rows,'human_judge_alignment':None,
        'cost':{'calls':len(calls),'reserved_usd':sum(c['reserve_usd'] for c in calls),
                'known_usd':sum(json.loads(c['body']).get('cost_usd') or 0 for c in calls),
                'unknown_cost_calls':sum(json.loads(c['body']).get('cost_usd') is None for c in calls)},
        'limitations':['입력 근거에 대한 응답 충실도이며 사실성·정책 최신성·분류 정확도가 아닙니다.',
            '한국어 독립 사람 평정과 judge 일치도는 미평가입니다.','저장된 모델 입력 전체를 근거로 사용하며 전체 도구 원문을 사후 추가하지 않습니다.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--store',type=Path,required=True)
    p.add_argument('--env',type=Path,required=True);p.add_argument('--other-ledger',type=Path,action='append',default=[])
    p.add_argument('--references',type=Path);p.add_argument('--data-mode',choices=['sample','local'],required=True)
    p.add_argument('--role',choices=['workflow_analyst','workflow_matching','policy_decision'],action='append');args=p.parse_args()
    if not args.store.is_file():p.error('use the existing cumulative ledger, not a new database')
    historical=[args.store.parent.parent / mode / 'events.sqlite3' for mode in ('sample','local')]
    ledgers=list({p.resolve() for p in historical+args.other_ledger if p.exists()}-{args.store.resolve()})
    if any(not p.is_file() for p in args.other_ledger):p.error('explicit historical ledger missing')
    settings=Settings(_env_file=args.env,data_mode=args.data_mode)
    result=asyncio.run(evaluate(args.folder,EventStore(args.store,settings.data_mode),settings,ledgers,
        json.loads(args.references.read_text()) if args.references else None,args.role))
    output=args.folder/('grounding-'+result['judge_run_id']+'.json')
    with output.open('x') as file:file.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(output)


if __name__=='__main__':main()
