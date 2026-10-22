"""Paired fake protocol comparison. It measures invariants/calls, not model quality."""
import json
import hashlib
import subprocess
import time
from datetime import datetime,timezone
from uuid import uuid4
from backend.app.config import ROOT,Settings
from backend.app.contracts import Scenario
from backend.agents.regional import context,collaborate,issues
from backend.events import EventStore
from backend.graph import GraphService
from backend.tools.neighborhoods import group_analysis
from backend.tools.weekly_signals import load as weekly
from backend.tools.indicators import digest


def run():
    id=str(uuid4());settings=Settings(_env_file=None,data_mode='sample',llm_mode='fake',person_mcp_mode='stub',resource_catalog='fixture',evaluation_id=id,llm_max_calls=4)
    store=EventStore(settings.runtime_dir/'events.sqlite3');service=GraphService(store,settings)
    weeks=weekly(settings)['weeks'];results=[];input_hashes={}
    for month in (f'2025-{m:02}' for m in range(7,13)):
        analysis=group_analysis(settings,max(w for w in weeks if w.startswith(month)),'20s')
        analysis['segments']=[r for r in analysis['segments'] if r['preferred'] and r['ym']==month]
        observations=context(analysis,'sample');input_hashes[month]=digest(observations)
        for method in ('single','collaboration'):
            scenario=Scenario(id=f'{month}-{method}',type='monthly',sim_time=f'{month}-28T00:00:00+09:00',payload={'ym':month})
            current=service.register(scenario);started=time.monotonic();error=None
            try:
                if method=='single':
                    plan=service.agents.call(current.id,scenario.sim_time,'regional_analyst',{'observations':observations,'previous_plan':None,'feedback':[],'round':1}).model_dump()
                    output={'status':'submitted','plan':plan,'rounds':[]}
                else:
                    def emit(key,sender,recipient,payload):
                        store.append_trace(current.id,scenario.sim_time,'agent_message',{'sender':sender,'recipient':recipient,**payload},sender)
                    output=collaborate(service.agents,current.id,scenario.sim_time,observations,emit)
                plan=output.get('plan');violations=issues(plan,observations) if plan else ['no reviewed plan']
            except Exception as exc:
                error=type(exc).__name__;output={'status':'failed','plan':None,'rounds':[]};violations=['execution failed']
            traces=store.traces(current.id,limit=1000)
            latency=(time.monotonic()-started)*1000
            with store.connection(write=True) as db:
                service.update_run(db,current.id,status='failed' if error else 'completed',ended_at=datetime.now(timezone.utc))
            results.append({'month':month,'method':method,'status':output['status'],'violations':violations,'plan':output['plan'],
                            'revisions':max(0,len(output['rounds'])-1),'calls':sum(t['kind']=='llm_call' for t in traces),
                            'latency_ms':latency,'cost_usd':sum(t['payload'].get('cost_usd',0) or 0 for t in traces if t['kind']=='llm_result'),
                            'error':error,'input_hash':input_hashes[month]})
    metrics={}
    for method in ('single','collaboration'):
        rows=[r for r in results if r['method']==method]
        metrics[method]={'cases':len(rows),'contract_passed':sum(not r['violations'] for r in rows),'failures':sum(r['error'] is not None or r['status']=='needs_human' for r in rows),
            'model_calls':sum(r['calls'] for r in rows),'revisions':sum(r['revisions'] for r in rows),'known_cost_usd':sum(r['cost_usd'] for r in rows),
            'mean_latency_ms':sum(r['latency_ms'] for r in rows)/len(rows),'content_quality':None}
    files=['eval/run_collaboration.py','backend/agents/regional.py','backend/agents/llm.py','backend/agents/schemas.py','backend/prompts/regional_analyst.txt','backend/prompts/regional_reviewer.txt']
    summary={'schema_version':'4','id':id,'created_at':datetime.now(timezone.utc).isoformat(),'data_mode':'sample','llm_mode':'fake',
        'status':'executed_collaboration_protocol','evaluated_scenarios':6,'metrics':metrics,'collaboration':{'paired_results':results},
        'results':[],'uncompleted':[r['month']+'-'+r['method'] for r in results if r['violations']],
        'stage_reproducibility':{'repetitions':1,'identical':None},
        'metadata':{'suite':'regional-collaboration-protocol-1','input_hashes':input_hashes,'model':'fake-v1','call_limit_per_method':4,
            'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'code_hash':digest({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}),
            'code_dirty':bool(subprocess.check_output(['git','status','--porcelain','--',*files],cwd=ROOT,text=True).strip()),
            'result_hash':digest([{k:v for k,v in r.items() if k!='latency_ms'} for r in results]),'scenario_count_basis':'six paired months, two methods each'},
        'limitations':['동일 월별 근거와 동일 역할 모델·호출 상한으로 단일 제안과 협업을 비교합니다.',
            'fake 통신 계약 평가이며 실제 LLM 내용 품질·협업 효과는 N/A입니다. 통과율을 지능의 증거로 쓰지 않습니다.',
            '개인 판단·실제 예산 배분은 하지 않습니다. 지연은 프로세스 내부 측정이며 네트워크/브라우저 수신 시간이 아닙니다.',
            '기본 fake는 오류 없는 fixture입니다. 수정 루프의 오류 주입은 단위 테스트로 따로 검증합니다.']}
    folder=ROOT/'eval/reports'/datetime.now(timezone.utc).strftime('%Y%m%d')/id;folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'report':str(folder.relative_to(ROOT)),'metrics':metrics},ensure_ascii=False))
    return summary


if __name__=='__main__':
    if run()['uncompleted']:raise SystemExit(2)
