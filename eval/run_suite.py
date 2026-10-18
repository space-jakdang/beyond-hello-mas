"""Run fixed public scenarios through an isolated HTTP service and a real browser receiver."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from backend.app.config import ROOT, Settings
from backend.app.contracts import Scenario, EvaluationLabel
from backend.events import EventStore
from backend.tools.catalog import load_catalog
from backend.tools.indicators import digest
from backend.tools.segments import load_segments
from backend.tools.staging import classify
from eval.metrics import summarize
from eval.observe import observe


def inputs():
    scenarios=[Scenario.model_validate(s) for s in json.loads((ROOT/'scenarios/inputs.json').read_text())]
    raw=json.loads((ROOT/'scenarios/labels.json').read_text())
    labels={}
    for label in raw:
        EvaluationLabel.model_validate({k:v for k,v in label.items() if k!='decision'})
        if label['decision'] not in ('approved','rejected') or label['scenario_id'] in labels:
            raise ValueError('invalid or duplicate decision label')
        labels[label['scenario_id']]=label
    if len(scenarios)!=40 or len({s.id for s in scenarios})!=40 or set(labels)!={s.id for s in scenarios}:
        raise ValueError('suite requires forty unique inputs and exactly matching labels')
    return scenarios,labels


def read_ratings(path, labels):
    rows=json.loads(path.read_text()) if path else []
    seen=set()
    for row in rows:
        id=row.get('scenario_id')
        if id not in labels or not id.startswith('S2-') or id in seen or type(row.get('score')) is not int or not 1<=row['score']<=5 or not row.get('reviewer'):
            raise ValueError('invalid, duplicate or anonymous human rating')
        seen.add(id)
    return rows


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=5)


def wait_health(client, process):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        if process.poll() is not None: raise RuntimeError('evaluation server exited')
        try:
            if client.get('/health').status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(.1)
    raise TimeoutError('evaluation server startup timeout')


def run_suite(settings, browser=True, timeout=30, ratings_path=None):
    scenarios,labels=inputs()
    ratings=read_ratings(ratings_path,labels)
    suite_id=str(uuid4())
    settings=settings.model_copy(update={'evaluation_id':suite_id})
    runtime=settings.runtime_dir; runtime.mkdir(parents=True,exist_ok=False)
    report_root=ROOT/'eval'/('reports' if settings.data_mode=='sample' else 'local')
    report_dir=report_root/datetime.now(timezone.utc).strftime('%Y%m%d')/suite_id
    report_dir.mkdir(parents=True,exist_ok=False)
    env={**os.environ,'DATA_MODE':settings.data_mode,'LLM_MODE':settings.llm_mode,'RESOURCE_CATALOG':settings.resource_catalog,'EVALUATION_ID':suite_id}
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1',0));port=port_socket.getsockname()[1]
    client_id='eval-'+suite_id
    server=receiver=None
    runs={};errors={};statuses={};receiver_error=None;setup_error=None
    with (runtime/'server.log').open('w') as log, httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=min(timeout,5)) as client:
        try:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app.main:create_app','--factory','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
            wait_health(client,server)
            if browser:
                receiver=subprocess.Popen(['node','frontend/eval-receiver.mjs',str(client.base_url).rstrip('/'),client_id],cwd=ROOT,stdout=subprocess.PIPE,stderr=log,text=True)
                ready=select.select([receiver.stdout],[],[],20)[0]
                if not ready or receiver.stdout.readline().strip()!='READY':
                    receiver_error='browser receiver unavailable';stop(receiver);receiver=None
            for scenario in scenarios:
                deadline=time.monotonic()+timeout
                receipt_deadline=None
                try:
                    response=client.post('/scenarios/run',json=scenario.model_dump(mode='json'));response.raise_for_status()
                    run=response.json();runs[scenario.id]=run
                    while time.monotonic()<deadline:
                        response=client.get('/runs/'+run['id']);response.raise_for_status();run=response.json();runs[scenario.id]=run
                        if run['status']=='awaiting_approval':
                            if receiver and receiver.poll() is not None:
                                receiver_error='browser receiver exited';receiver=None
                            if receiver:
                                if receipt_deadline is None:receipt_deadline=time.monotonic()+min(3,timeout/2)
                                traces=client.get(f"/runs/{run['id']}/traces?limit=1000").json()
                                if time.monotonic()<receipt_deadline and not any(t['kind']=='received' and t['payload']['client_id']==client_id for t in traces):
                                    time.sleep(.05);continue
                            review=client.get(f"/runs/{run['id']}/approval");review.raise_for_status()
                            decision=labels[scenario.id]['decision']
                            response=client.post(f"/runs/{run['id']}/decision",json={'snapshot_version':review.json()['approval']['snapshot_version'],'status':decision,'operator':'evaluation-fixture','reason':'fixed evaluation rejection' if decision=='rejected' else None},timeout=timeout)
                            response.raise_for_status()
                        elif run['status'] in ('completed','rejected','failed'):
                            statuses[scenario.id]=run['status'];break
                        else:time.sleep(.05)
                    else:raise TimeoutError('scenario deadline')
                except Exception as exc:
                    errors[scenario.id]=type(exc).__name__;statuses[scenario.id]='timeout' if isinstance(exc,(TimeoutError,httpx.TimeoutException)) else 'failed'
            if receiver:time.sleep(.5)
        except Exception as exc:
            setup_error=type(exc).__name__
        finally:
            stop(receiver);stop(server)
    store=EventStore(runtime/'events.sqlite3',settings.data_mode)
    results=[]
    for scenario in scenarios:
        run=runs.get(scenario.id,{})
        traces=store.traces(run['id'],limit=10000) if run else []
        proposal={}
        if run:
            with store.connection() as db:
                row=db.execute('SELECT proposal FROM approvals WHERE run_id=?',(run['id'],)).fetchone()
                if row:proposal=json.loads(row[0])
        results.append(observe(scenario,labels[scenario.id],run,traces,proposal,statuses.get(scenario.id,'not_run'),errors.get(scenario.id) or setup_error,client_id))
    try:
        rows,source=load_segments(settings)
        repetitions=[digest([(s['ym'],s['dong_cd'],s['age_band'],s['stage']) for s in classify(rows)['segments']]) for _ in range(3)]
        reproducibility={'repetitions':3,'hashes':repetitions,'identical':len(set(repetitions))==1,'source':source}
    except Exception as exc:reproducibility={'error':type(exc).__name__,'repetitions':0,'identical':None}
    metrics=summarize(results,ratings)
    try:
        catalog=load_catalog(settings.catalog_path)
        catalog_metadata={'catalog_version':catalog[0].catalog_version if catalog else None,'catalog_hash':digest([r.model_dump(mode='json') for r in catalog])}
    except Exception as exc:catalog_metadata={'catalog_error':type(exc).__name__}
    prompts={p.name:digest(p.read_text()) for p in (ROOT/'backend/prompts').glob('*.txt')}
    summary={'schema_version':'1','id':suite_id,'created_at':datetime.now(timezone.utc).isoformat(),
             'status':'executed' if all(r['status'] in ('completed','rejected') for r in results) else 'partial',
             'data_mode':settings.data_mode,'llm_mode':settings.llm_mode,'model':settings.openai_model if settings.llm_mode=='live' else 'fake-v1',
             'evaluated_scenarios':len(results),'metrics':metrics,'results':results,'stage_reproducibility':reproducibility,
             'metadata':{'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'code_dirty':bool(subprocess.check_output(['git','diff','HEAD','--'],cwd=ROOT,text=True)),
                'inputs_hash':digest([s.model_dump(mode='json') for s in scenarios]),'labels_hash':digest(labels),'label_version':'development-1-unreviewed',
                **catalog_metadata,'prompts':prompts,
                'price_version':settings.price_version,'browser_receiver':bool(browser and not receiver_error and not setup_error),'receiver_error':receiver_error,'setup_error':setup_error},
             'uncompleted':['independent human labels']+(['human suitability ratings'] if len(ratings)<16 else [])+(['OpenAI live evaluation'] if settings.llm_mode=='fake' else []),
             'limitations':['development labels; not validated detection accuracy','fake agent intentionally emits no cause predictions','small sample nearest-rank p95','automatic fixture decisions are not human response times']}
    (report_dir/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary,report_dir


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--data-mode',choices=['sample','local'],default='sample')
    parser.add_argument('--catalog',choices=['fixture','curated'],default='fixture')
    parser.add_argument('--without-browser',action='store_true')
    parser.add_argument('--timeout',type=float,default=30)
    parser.add_argument('--ratings',type=Path)
    args=parser.parse_args()
    if not 1<=args.timeout<=120:parser.error('timeout must be 1..120 seconds')
    settings=Settings(data_mode=args.data_mode,llm_mode='live' if args.live else 'fake',resource_catalog=args.catalog)
    summary,path=run_suite(settings,not args.without_browser,args.timeout,args.ratings)
    print(json.dumps({'status':summary['status'],'evaluated_scenarios':summary['evaluated_scenarios'],'path':str(path.relative_to(ROOT)),'id':summary['id']},ensure_ascii=False))
    return 0 if summary['status']=='executed' else 2
