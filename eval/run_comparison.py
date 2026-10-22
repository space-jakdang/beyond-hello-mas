"""A/B protocol runner. Live and C effectiveness are not claimed by this runner."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import time
from uuid import uuid4
from backend.agents.llm import Agents
from backend.agents.regional_worker import deterministic, single
from backend.app.config import ROOT, Settings
from backend.app.contracts import Run
from backend.events import EventStore
from backend.tools.indicators import digest


def load_cases(split):
    if split not in ('dev','test'):raise ValueError('unknown split')
    root=ROOT/'scenarios/comparison'
    contract=json.loads((root/'contract.json').read_text())
    for name,expected in contract['files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:raise ValueError('frozen case hash mismatch')
    cases=json.loads((root/f'{split}_inputs.json').read_text())
    if len(cases)!=contract['cases'][split] or len({c['id'] for c in cases})!=len(cases):raise ValueError('case count or duplicate mismatch')
    return contract,cases


def run(split='dev', study=False, live=False):
    if live and (not study or split!='test'):raise ValueError('live requires the locked test study')
    from backend.agents.regional_team import collaborate
    import random
    contract,cases=load_cases(split);id=str(uuid4())
    methods=contract['methods'] if study else ['deterministic','single']
    repetitions=contract['planned_live_repetitions'] if study else 1
    settings=Settings(data_mode='local',llm_mode='live',evaluation_id=None) if live else Settings(
        _env_file=None,data_mode='sample',llm_mode='fake',evaluation_id=id)
    if live and not all((settings.openai_model,settings.price_version,settings.input_usd_per_million,settings.output_usd_per_million)):
        raise ValueError('live comparison requires configured model and verified prices')
    settings.llm_max_calls=contract['max_calls_per_method'];settings.llm_run_budget_usd=contract['max_cost_usd_per_run']
    # Live uses the existing local ledger. A fresh evaluation DB would reset cumulative spending.
    store=EventStore(settings.runtime_dir/'events.sqlite3',settings.data_mode);agents=Agents(store,settings)
    folder=settings.runtime_dir/'comparison-studies'/id if live else settings.runtime_dir
    folder.mkdir(parents=True,exist_ok=True)
    with store.connection() as db:reserved=db.execute('SELECT COALESCE(SUM(reserve_usd),0) FROM llm_calls').fetchone()[0]
    required=len(cases)*repetitions*sum(m!='deterministic' for m in methods)*contract['max_cost_usd_per_run']
    available=max(0,settings.llm_budget_usd-reserved)
    blocked=live and available<required
    results=[]
    for repetition in range(1,repetitions+1):
        for case in cases:
            order=list(methods)
            if study:random.Random(f"20261020/{repetition}/{case['id']}").shuffle(order)
            results.extend({'case_id':case['id'],'repetition':repetition,'method':method,'input_hash':digest(case),
                'output':{'status':'not_executed','plan':None,'reason':'not_started'},'run_id':None,
                'calls':0,'latency_seconds':None,'cost_usd':None,'reserved_usd':0,'content_rating':None} for method in order)
    files=['eval/rate_comparison.py','eval/run_comparison.py','backend/agents/regional_worker.py','backend/agents/regional_team.py','backend/agents/regional.py',
        'backend/agents/llm.py','backend/agents/schemas.py','backend/prompts/regional_worker.txt','backend/prompts/regional_planner.txt',
        'backend/prompts/regional_audit.txt','backend/app/config.py','scripts/generate_comparison.py','scenarios/comparison/contract.json']
    report={'id':id,'suite':contract['version'],'split':split,'mode':settings.llm_mode,'status':'running',
        'case_count':len(cases),'repetitions':repetitions,'methods_run':methods,
        'methods_not_run':[m for m in contract['methods'] if m not in methods],
        'contract':contract,'contract_hash':digest(contract),'input_hash':contract['files'][f'{split}_inputs.json'],
        'label_hash':contract['files'][f'{split}_labels.json'],
        'code_hash':digest({f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}),
        'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'code_dirty':bool(subprocess.check_output(['git','status','--porcelain','--',*files],cwd=ROOT,text=True).strip()),
        'model':settings.openai_model if live else 'fake-v1',
        'pricing':{'version':settings.price_version,'input_per_million':settings.input_usd_per_million,'output_per_million':settings.output_usd_per_million} if live else None,
        'budget_preflight':{'blocked':blocked,'required_reservation_usd':required,'available_usd':available} if live else None,
        'rating_code_hash':hashlib.sha256((ROOT/'eval/rate_comparison.py').read_bytes()).hexdigest(),
        'quality':None,'adoption_decision':'not_evaluated','results':results,
        'limitations':contract['limitations']+['Fake runs verify contracts only; human content ratings required.',
            'Latency includes method persistence overhead; A has no model writes.',
            'C uses fixed evidence snapshots. Dynamic policy research and lookup/reviewer ablations are not evaluated.']}
    def save():
        temporary=folder/'comparison.tmp';temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        temporary.replace(folder/'comparison.json')
    save();inputs={c['id']:c for c in cases}
    try:
        for result in results:
            method=result['method'];case=inputs[result['case_id']]
            if blocked and method!='deterministic':
                result['output']['reason']='budget_preflight';save();continue
            if live and method!='deterministic':
                with store.connection() as db:current_reserved=db.execute('SELECT COALESCE(SUM(reserve_usd),0) FROM llm_calls').fetchone()[0]
                result['budget_available_before_run']=max(0,settings.llm_budget_usd-current_reserved)
                if result['budget_available_before_run']<contract['max_cost_usd_per_run']:
                    result['output']['reason']='budget_during_study';save();continue
            run_id=str(uuid4());now=datetime.now(timezone.utc);result['run_id']=run_id
            store.create_run(Run(id=run_id,thread_id=run_id,scenario_id=case['id'],status='running',data_mode=settings.data_mode,llm_mode=settings.llm_mode,
                input_version=contract['version'],rule_version='regional-1',model_version=report['model'],prompt_version=contract['version'],
                catalog_version='synthetic-snapshot-1',started_at=now))
            def emit(key,sender,recipient,payload):
                store.append_trace(run_id,now,'agent_message',{'sender':sender,'recipient':recipient,**payload},sender)
            started=time.monotonic(); interruption=None
            try:
                if method=='deterministic':output=deterministic(case['observations'])
                else:
                    worker=single if method=='single' else collaborate
                    output=worker(agents,run_id,now,case['observations'],case['snapshots'],emit,
                        max_calls=contract['max_calls_per_method'],timeout_seconds=contract['completion_deadline_seconds'])
            except BaseException as exc:
                output={'status':'failed','plan':None,'reason':type(exc).__name__}
                if not isinstance(exc,Exception):interruption=exc
            elapsed=time.monotonic()-started;traces=store.traces(run_id,limit=1000)
            with store.connection(write=True) as db:
                calls=db.execute('SELECT status,reserve_usd,body FROM llm_calls WHERE run_id=?',(run_id,)).fetchall()
                current=store.get_run(run_id).model_copy(update={'status':'failed' if output['status']=='failed' else 'completed','ended_at':datetime.now(timezone.utc)})
                db.execute('UPDATE runs SET body=? WHERE id=?',(current.model_dump_json(),run_id))
            costs=[json.loads(c['body']).get('cost_usd') for c in calls]
            result.update(output=output,calls=len(calls),latency_seconds=elapsed,
                          cost_usd=None if any(c is None for c in costs) else sum(costs),reserved_usd=sum(c['reserve_usd'] for c in calls))
            result['returned_models']=sorted({t['payload'].get('returned_model',report['model']) for t in traces if t['kind']=='llm_result'})
            save()
            if interruption is not None:raise interruption
        report['status']='budget_blocked' if blocked or any(r['output'].get('reason')=='budget_during_study' for r in results) else 'awaiting_human_ratings' if live else 'protocol_only'
    finally:
        if report['status']=='running':report['status']='interrupted'
        save()
    print(folder/'comparison.json')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--split',choices=('dev','test'),default='dev')
    parser.add_argument('--study',action='store_true');parser.add_argument('--live',action='store_true');args=parser.parse_args()
    run(args.split,args.study,args.live)
