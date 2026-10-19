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


def run(split='dev'):
    contract,cases=load_cases(split);id=str(uuid4())
    settings=Settings(_env_file=None,data_mode='sample',llm_mode='fake',evaluation_id=id,
                      llm_max_calls=contract['max_calls_per_method'])
    store=EventStore(settings.runtime_dir/'events.sqlite3');agents=Agents(store,settings);results=[]
    for case in cases:
        for method in ('deterministic','single'):
            run_id=str(uuid4());now=datetime.now(timezone.utc)
            store.create_run(Run(id=run_id,thread_id=run_id,scenario_id=case['id'],status='running',data_mode='sample',llm_mode='fake',
                input_version=contract['version'],rule_version='regional-1',model_version='fake-v1',prompt_version=contract['version'],
                catalog_version='synthetic-snapshot-1',started_at=now))
            def emit(key,sender,recipient,payload):
                store.append_trace(run_id,now,'agent_message',{'sender':sender,'recipient':recipient,**payload},sender)
            started=time.monotonic()
            output=deterministic(case['observations']) if method=='deterministic' else single(agents,run_id,now,case['observations'],case['snapshots'],emit,
                max_calls=contract['max_calls_per_method'],timeout_seconds=contract['completion_deadline_seconds'])
            elapsed=time.monotonic()-started;traces=store.traces(run_id,limit=1000)
            current=store.get_run(run_id).model_copy(update={'status':'completed','ended_at':datetime.now(timezone.utc)})
            with store.connection(write=True) as db:db.execute('UPDATE runs SET body=? WHERE id=?',(current.model_dump_json(),run_id))
            results.append({'case_id':case['id'],'method':method,'input_hash':digest(case),'output':output,
                            'calls':sum(t['kind']=='llm_call' for t in traces),'latency_seconds':elapsed,'cost_usd':0,
                            'content_rating':None})
    files=['eval/run_comparison.py','backend/agents/regional_worker.py','backend/agents/regional.py','backend/agents/llm.py',
           'backend/agents/schemas.py','backend/prompts/regional_worker.txt']
    report={'id':id,'suite':contract['version'],'split':split,'mode':'fake','status':'protocol_only',
            'case_count':len(cases),'methods_run':['deterministic','single'],'methods_not_run':['collaboration'],
            'contract_hash':digest(contract),'input_hash':contract['files'][f'{split}_inputs.json'],
            'label_hash':contract['files'][f'{split}_labels.json'],
            'code_hash':digest({f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}),
            'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'code_dirty':bool(subprocess.check_output(['git','status','--porcelain','--',*files],cwd=ROOT,text=True).strip()),
            'quality':None,'adoption_decision':'not_evaluated','results':results,
            'limitations':contract['limitations']+['Fake runs verify contracts only. No live cost or quality evidence.']}
    (settings.runtime_dir/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print((settings.runtime_dir/'comparison.json').relative_to(ROOT))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--split',choices=('dev','test'),default='dev');args=parser.parse_args()
    run(args.split)
