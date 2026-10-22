"""Local evaluation jobs: frozen private inputs, durable claim, no paid auto-retry."""
import asyncio
import json
import sqlite3
from importlib.util import find_spec
from uuid import UUID, uuid4
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from backend.events import utcnow
from backend.tools.indicators import digest
from backend.app import config
from backend.app.quality_reports import quality_root, quality_detail, quality_body

VERSION='quality-job-2'


class JobRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    suite: Literal['deterministic','grounding']='deterministic'


class QualityJobs:
    def __init__(self,store,settings):
        self.store,self.settings=store,settings
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS quality_jobs (id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, body TEXT NOT NULL)')

    def recover(self):
        # shortcut: one local app process, use leases before supporting multiple workers.
        with self.store.connection(write=True) as db:
            for row in db.execute("SELECT id,body FROM quality_jobs WHERE json_extract(body,'$.status') IN ('running','pending')").fetchall():
                body=json.loads(row['body']);body.update(status='failed',error='interrupted_no_automatic_retry',ended_at=utcnow().isoformat())
                db.execute('UPDATE quality_jobs SET body=? WHERE id=?',(json.dumps(body),row['id']))

    def get(self,identifier):
        with self.store.connection() as db:
            row=db.execute('SELECT body FROM quality_jobs WHERE id=?',(str(identifier),)).fetchone()
        if row is None:raise HTTPException(404,'evaluation job not found')
        return json.loads(row['body'])

    def public(self,body):
        return {k:v for k,v in body.items() if k not in ('snapshot','judge_config')}

    def history(self,report_id,source):
        with self.store.connection() as db:
            rows=db.execute("SELECT body FROM quality_jobs WHERE json_extract(body,'$.report_id')=? AND json_extract(body,'$.source')=? ORDER BY rowid DESC",(str(report_id),source)).fetchall()
        return [self.public(json.loads(r['body'])) for r in rows]

    def preflight(self,report_id,source):
        report=quality_detail(self.settings,source,report_id)
        reasons=[];settings=self.settings
        if source!='current':reasons.append('유료 근거 평가는 현재 서버 자료에서만 실행합니다.')
        if settings.evaluation_id:reasons.append('격리 평가 장부에서는 누적 유료 평가를 실행하지 않습니다.')
        if settings.llm_mode!='live' or not all((settings.openai_model,settings.input_usd_per_million,settings.output_usd_per_million,settings.price_version,settings.llm_budget_usd)):
            reasons.append('live 모델·가격·누적 예산 설정이 필요합니다.')
        if find_spec('ragas') is None:reasons.append('evaluation 선택 의존성을 설치해야 합니다.')
        path=quality_root(settings,source)/str(report_id)/'predictions.json'
        source_calls=0
        if path.exists():
            predictions=json.loads(path.read_text())
            run_ids={p.get('run_id') for p in predictions['predictions'] if p.get('run_id')}
            with self.store.connection() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_calls'").fetchone():
                    for run_id in run_ids:
                        source_calls+=db.execute("SELECT COUNT(*) FROM llm_calls WHERE run_id=? AND status='ok' AND json_extract(body,'$.mode')='live' AND role IN ('workflow_analyst','workflow_matching','policy_decision','policy_design')",(run_id,)).fetchone()[0]
        if not source_calls:reasons.append('현재 장부에 평가 가능한 실제 모델 입력·응답이 없습니다.')
        reserved=0.0
        ledgers={self.store.path.resolve()}|{(self.store.path.parent.parent/m/'events.sqlite3').resolve() for m in ('sample','local')}
        try:
            for ledger in ledgers:
                if not ledger.exists():continue
                with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as db:
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_calls'").fetchone():
                        reserved+=db.execute('SELECT COALESCE(SUM(reserve_usd),0) FROM llm_calls').fetchone()[0]
        except sqlite3.Error:
            reserved=None
            reasons.append('누적 비용 장부를 읽지 못했습니다.')
        remaining=max(0,settings.llm_budget_usd-reserved) if reserved is not None else None
        if remaining is not None and remaining<=0:reasons.append('누적 예산의 잔여액이 없습니다.')

        maximum=None
        if settings.input_usd_per_million and settings.output_usd_per_million:
            maximum=settings.llm_max_calls*((settings.llm_max_input_bytes+8192)*settings.input_usd_per_million+settings.llm_max_output_tokens*settings.output_usd_per_million)/1e6
            if settings.llm_run_budget_usd is not None:maximum=min(maximum,settings.llm_run_budget_usd)
        return {'deterministic_usd':0,'grounding_max_reservation_usd':maximum,'reserved_usd':reserved,'remaining_usd':remaining,'recorded_source_calls':source_calls,'grounding_available':not reasons,
            'grounding_reasons':reasons,'readiness':report['readiness'],
            'limitations':['결정적 평가는 모델을 호출하지 않습니다. 기준답 없는 항목은 미평가로 저장합니다.',
                '근거 평가는 호출마다 기존 누적 장부 잔여 예산을 확인합니다. 상한은 견적이며 공급자 실측 비용은 별도 기록합니다.',
                '동일 자료·평가 설정은 기존 실행을 반환하며 실패를 자동 재시도하지 않습니다.',
                '화면의 RAGAS 실행은 Faithfulness를 계산합니다. 참조 기반 Context Precision/Recall은 기준답을 지정한 CLI로 실행합니다.']}

    def register(self,report_id,source,suite):
        preflight=self.preflight(report_id,source)
        if suite=='grounding' and not preflight['grounding_available']:raise HTTPException(409,'; '.join(preflight['grounding_reasons']))
        folder=quality_root(self.settings,source)/str(report_id)
        snapshot={}
        for name in ('inputs.json','labels.json','predictions.json','study.json','policy-candidates.json','policy-drafts.json','policy-draft-ratings.json'):
            path=folder/name
            if path.is_symlink():raise HTTPException(409,'evaluation input symlink not allowed')
            if path.exists():snapshot[name]=json.loads(path.read_text())
        judge_config={k:getattr(self.settings,k) for k in ('openai_model','llm_max_calls','llm_max_input_bytes','llm_max_output_tokens','llm_budget_usd','llm_run_budget_usd','input_usd_per_million','output_usd_per_million','price_version')} if suite=='grounding' else {}
        study=snapshot.get('study.json')
        comparison_key=digest({'dataset':snapshot['inputs.json']['dataset_hash'],'labels':snapshot['labels.json'],
            'suite':suite,'version':VERSION,'judge':judge_config,'policy_ratings':snapshot.get('policy-draft-ratings.json'),
            'study_protocol':{k:v for k,v in study.items() if k!='arms'} if study else None})
        key=digest({'version':VERSION,'report_id':str(report_id),'source':source,'snapshot':snapshot,'suite':suite,'judge':judge_config})
        with self.store.connection(write=True) as db:
            old=db.execute('SELECT body FROM quality_jobs WHERE request_key=?',(key,)).fetchone()
            if old:return self.public(json.loads(old['body']))
            body={'id':str(uuid4()),'report_id':str(report_id),'source':source,'suite':suite,'version':VERSION,
                'comparison_key':comparison_key,'judge_model':judge_config.get('openai_model'),'judge_price_version':judge_config.get('price_version'),
                'status':'pending','created_at':utcnow().isoformat(),'ended_at':None,'error':None,'result':None,
                'snapshot':snapshot,'judge_config':judge_config,'input_key':key,'estimate':preflight}
            db.execute('INSERT INTO quality_jobs VALUES (?,?,?)',(body['id'],key,json.dumps(body,ensure_ascii=False)))
        return self.public(body)

    def execute(self,identifier):
        with self.store.connection(write=True) as db:
            row=db.execute('SELECT body FROM quality_jobs WHERE id=?',(identifier,)).fetchone()
            if not row:return
            body=json.loads(row['body'])
            if body['status']!='pending':return
            body['status']='running';db.execute('UPDATE quality_jobs SET body=? WHERE id=?',(json.dumps(body),identifier))
        phase='inputs'
        try:
            mode='sample' if body['source']=='sample' else self.settings.data_mode
            folder=self.settings.runtime_root/'quality-jobs'/mode/identifier;folder.mkdir(parents=True,exist_ok=False)
            for name,data in body['snapshot'].items():
                with (folder/name).open('x') as file:file.write(json.dumps(data,ensure_ascii=False))
            # Validate frozen inputs before any paid call, including changes during registration.
            quality_body(folder,mode,body['report_id'])
            if body['suite']=='grounding':
                phase='judge'
                from eval.run_grounding import evaluate
                ledgers=[self.store.path.parent.parent/m/'events.sqlite3' for m in ('sample','local')]
                settings=self.settings.model_copy(update=body['judge_config'])
                result=asyncio.run(evaluate(folder,self.store,settings,[p for p in ledgers if p.exists() and p.resolve()!=self.store.path.resolve()]))
                with (folder/('grounding-'+result['judge_run_id']+'.json')).open('x') as file:file.write(json.dumps(result,ensure_ascii=False))
            phase='result'
            body['result']=quality_body(folder,mode,body['report_id'])
            body['status']='completed'
        except Exception as error:
            body['status']='failed';body['error']=type(error).__name__;body['error_phase']=phase
        body['ended_at']=utcnow().isoformat()
        with self.store.connection(write=True) as db:
            # A recovered interrupted job cannot be overwritten by an old worker.
            db.execute("UPDATE quality_jobs SET body=? WHERE id=? AND json_extract(body,'$.status')='running'",(json.dumps(body,ensure_ascii=False),identifier))


def quality_job_router(jobs):
    router=APIRouter()

    @router.get('/reports/quality/{report_id}/preflight')
    def preflight(report_id:UUID,source:Literal['current','sample']='current'):
        return jobs.preflight(report_id,source)

    @router.get('/reports/quality/{report_id}/jobs')
    def history(report_id:UUID,source:Literal['current','sample']='current'):
        return jobs.history(report_id,source)

    @router.post('/reports/quality/{report_id}/jobs',status_code=202)
    def start(report_id:UUID,body:JobRequest,background:BackgroundTasks,response:Response,source:Literal['current','sample']='current'):
        try:job=jobs.register(report_id,source,body.suite)
        except (ValueError,KeyError,OSError):raise HTTPException(409,'invalid evaluation inputs')
        if job['status']=='pending':background.add_task(jobs.execute,job['id'])
        response.status_code=202 if job['status'] in ('pending','running') else 200
        return job

    @router.get('/reports/quality/{report_id}/evidence')
    def evidence(report_id:UUID,case_id:str,source:Literal['current','sample']='current'):
        return case_evidence(jobs,report_id,case_id,source)

    @router.get('/quality-jobs/{identifier}')
    def job(identifier:UUID):
        return jobs.public(jobs.get(identifier))

    return router


def case_evidence(jobs,report_id,case_id,source):
    quality_detail(jobs.settings,source,report_id)
    if source=='sample' and jobs.settings.data_mode!='sample':
        return {'run_id':None,'rows':[],'reason':'현재 서버와 평가 자료 모드가 달라 원래 실행에 연결하지 않습니다.'}
    folder=quality_root(jobs.settings,source)/str(report_id)
    from eval.quality_metrics import validate_predictions
    from eval.quality_contracts import load_frozen
    frozen=json.loads((folder/'inputs.json').read_text());dataset=load_frozen(frozen)
    case=next((c for c in dataset.cases if c.id==case_id),None)
    if case is None:raise HTTPException(404,'evaluation case not found')
    path=folder/'predictions.json'
    predictions=validate_predictions(frozen,json.loads(path.read_text())) if path.exists() else None
    row=next((p for p in predictions.predictions if p.case_id==case_id),None) if predictions else None
    run_id=row.run_id if row else None
    evidence_id=case.facts.get('evidence_id')
    if not run_id or not evidence_id:return {'run_id':None,'rows':[],'reason':'원래 실행 ID 또는 관측 근거 ID가 기록되지 않았습니다.'}
    try:
        UUID(run_id);run=jobs.store.get_run(run_id)
    except (ValueError,KeyError):return {'run_id':None,'rows':[],'reason':'이 서버에서 원래 실행을 찾지 못했습니다.'}
    if run.data_mode!=jobs.settings.data_mode:raise HTTPException(409,'source run mode differs')
    with jobs.store.connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='approvals'").fetchone():proposal=None
        else:proposal=db.execute('SELECT proposal FROM approvals WHERE run_id=?',(run_id,)).fetchone()
    assignments=json.loads(proposal[0]).get('assignments',[]) if proposal else []
    selected=[a for a in assignments if a.get('evidence_id')==evidence_id]
    return {'run_id':run_id,'reason':'원래 실행의 기록입니다. 가져온 평가 예측과 다를 수 있으며 사후 설명을 생성하지 않습니다.' if selected else '해당 관측 근거의 자원 제안 기록이 없습니다.',
        'rows':[{'decision_evidence':a.get('decision_evidence'),'selected_ids':[p['id'] for p in a.get('recommendations',[])],
            'excluded':a.get('excluded',[]),'held':not a.get('recommendations')} for a in selected]}
