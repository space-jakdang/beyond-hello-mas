"""RAGAS over recorded, grounded explanations only; never score templates."""
import argparse
import asyncio
import json
import math
from pathlib import Path
from uuid import UUID
from backend.tools.indicators import digest
from backend.policy.alternatives import model_context
from eval.alternative_quality import quality


async def evaluate(store,settings,owner,other_ledgers=()):
    from eval.ragas_judge import BudgetedJudge
    from ragas import SingleTurnSample
    from ragas.metrics import Faithfulness
    with store.connection() as db:
        sets=[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=? ORDER BY dong_cd',(owner,))]
        calls=[json.loads(r[0]) for r in db.execute("SELECT body FROM llm_calls WHERE role='policy_alternatives' AND status='ok'")]
    if not sets:raise ValueError('no policy alternatives')
    report=quality(sets);rows=[];judge=None
    with store.connection(write=True) as db:
        db.execute('CREATE TABLE IF NOT EXISTS alternative_grounding (owner_id TEXT,input_hash TEXT,body TEXT,PRIMARY KEY(owner_id,input_hash))')
        previous=db.execute('SELECT body FROM alternative_grounding WHERE owner_id=? AND input_hash=?',(owner,report['input_hash'])).fetchone()
        if previous:return json.loads(previous[0])
        db.execute('INSERT INTO alternative_grounding VALUES (?,?,?)',(owner,report['input_hash'],json.dumps({'state':'pending','rows':[],'input_hash':report['input_hash'],'limitation':'평가 진행 중 또는 중단됨. 자동 유료 재시도하지 않습니다.'})))
    try:
        for body in sets:
            expected=model_context(body['evidence'])
            call=next((c for c in calls if c.get('mode')=='live' and c.get('input')==expected),None)
            for alternative in body['alternatives']:
                eligible=next(r['grounding_eligible'] for r in report['rows'] if r['alternative_id']==alternative['id'])
                row={'alternative_id':alternative['id'],'value':None,'state':'not_evaluated','reason':'no_recorded_grounded_explanation'}
                if eligible and call:
                    original=next((a for a in call['output']['alternatives'] if a['strategy']==alternative['strategy']),None)
                    if original and original['rationale']==alternative['rationale']:
                        judge=judge or BudgetedJudge(store,settings,other_ledgers)
                        sample=SingleTurnSample(user_input='제안 근거 설명이 주어진 지역·정책 자료에 충실한가?',response=original['rationale'],retrieved_contexts=[json.dumps(call['input'],ensure_ascii=False)])
                        try:
                            value=float(await Faithfulness(llm=judge).single_turn_ascore(sample))
                            row.update(value=value if math.isfinite(value) else None,state='evaluated' if math.isfinite(value) else 'not_evaluated',reason='recorded_rationale_only',source_hash=digest(call))
                        except Exception as exc:row.update(state='failed',reason=type(exc).__name__)
                rows.append(row)
    finally:
        if judge:judge.finish(any(r['state']=='failed' for r in rows))
    result={'state':'partial' if any(r['state']=='failed' for r in rows) else 'completed','input_hash':report['input_hash'],'rows':rows,'judge_run_id':judge.run_id if judge else None,'ragas_version':'0.4.3','human_alignment':None,
            'limitation':'생성 당시 입력에 대한 제안 근거 설명 충실도입니다. 신규 운영안의 효과·사실성·실현 가능성은 평가하지 않습니다.'}
    with store.connection(write=True) as db:
        costs=[json.loads(row[0]) for row in db.execute('SELECT body FROM llm_calls WHERE run_id=?',(judge.run_id,))] if judge else []
        result['cost']={'calls':len(costs),'known_usd':sum(c.get('cost_usd') or 0 for c in costs),'unknown_cost_calls':sum(c.get('cost_usd') is None for c in costs),'price_versions':sorted({c['price_version'] for c in costs if c.get('price_version')})}
        db.execute('UPDATE alternative_grounding SET body=? WHERE owner_id=? AND input_hash=?',(json.dumps(result,ensure_ascii=False),owner,report['input_hash']))
    return result


def main():
    from backend.app.config import Settings
    from backend.events import EventStore
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('owner_id',type=UUID);p.add_argument('--store',type=Path,required=True);p.add_argument('--env',type=Path,required=True);p.add_argument('--data-mode',choices=['sample','local'],required=True);p.add_argument('--other-ledger',type=Path,action='append',default=[])
    args=p.parse_args()
    if not args.store.is_file():p.error('use existing cumulative ledger')
    settings=Settings(_env_file=args.env,data_mode=args.data_mode,llm_mode='live')
    result=asyncio.run(evaluate(EventStore(args.store,args.data_mode),settings,str(args.owner_id),args.other_ledger))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
