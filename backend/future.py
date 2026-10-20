"""A durable, one-shot queue of synthetic future periods; never overwrites observations."""
import json
import random
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from backend.app.contracts import Scenario, SegmentV3
from backend.events import utcnow
from backend.tools.indicators import digest
from backend.tools.segments_v3 import load_segments

VERSION='synthetic-future-1'
SEED=20261021


class FutureSegment(SegmentV3):
    ym: str = Field(pattern=r'^20\d{2}-(0[1-9]|1[0-2])$')


class FutureRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    sgg:Literal['11230','32010']


def today():
    return datetime.now(ZoneInfo('Asia/Seoul')).date()


def future_months(day):
    index=day.year*12+day.month-1
    return [f'{(index+n)//12:04d}-{(index+n)%12+1:02d}' for n in (1,2,3)]


def read_snapshot(settings,identifier):
    identifier=str(UUID(str(identifier)))
    with closing(sqlite3.connect(f'file:{settings.runtime_dir / "events.sqlite3"}?mode=ro',uri=True)) as db:
        row=db.execute('SELECT body FROM future_batches WHERE id=?',(identifier,)).fetchone()
    if row is None:raise ValueError('future scenario not found')
    body=json.loads(row[0])
    if body['data_mode']!=settings.data_mode or body['input_hash']!=digest({'inputs':body['inputs'],'signals':body['signals']}):
        raise ValueError('future scenario integrity mismatch')
    return body


def scenario_rows(settings,task):
    body=read_snapshot(settings,task.future_id)
    if (task.sgg,task.sex,task.age_group,task.as_of.isoformat())!=(body['sgg'],body['sex'],body['age_group'],body['as_of']) or task.ym not in body['months']:
        raise ValueError('task differs from frozen future scenario')
    rows=[FutureSegment.model_validate(r) for r in body['inputs']]
    return rows,{'synthetic':True,'generator_version':VERSION,'seed':body['seed'],
                 'baseline_input_hash':body['baseline_input_hash'],'future_input_hash':body['input_hash']},body


def create_batch(service,request):
    identifier=str(request.request_id)
    with service.store.connection() as db:
        existing=db.execute('SELECT body FROM future_batches WHERE id=?',(identifier,)).fetchone()
    if existing:
        body=json.loads(existing[0])
        if body['llm_mode']!=service.settings.llm_mode:raise ValueError('restore original LLM mode')
        if body['sgg']!=request.sgg:raise ValueError('request id already used for another region')
        return body
    rows,metadata=load_segments(service.settings)
    region=[r for r in rows if r.sgg==request.sgg and r.sex=='M' and r.age_group=='youth' and r.preferred]
    if not region:raise ValueError('no regional baseline')
    # For monthly sources use the latest known month; aggregate sources retain their original scope.
    latest=max((r.ym for r in region if r.ym),default=None)
    baseline=[r for r in region if r.ym in (None,latest)]
    if len({r.dong_cd for r in baseline})!=len(baseline):raise ValueError('ambiguous baseline per dong')
    day=today();months=future_months(day);rng=random.Random(SEED)
    inputs=[];signals={}
    for month in months:
        signals[month]={}
        for row in sorted(baseline,key=lambda r:r.dong_cd):
            value=None if row.value is None else round(row.value+rng.uniform(-.06,.06),6)
            generated=row.model_copy(update={'ym':month,'value':value,
                'source_period':f'합성 미래 시나리오 {month} · 기준자료: {row.source_period}',
                'flags':[*row.flags,'synthetic_future','not_a_forecast']})
            inputs.append(FutureSegment.model_validate(generated.model_dump()).model_dump(mode='json'))
            signals[month][row.dong_cd]=[rng.choice(['none','weak','strong']) for _ in range(2)]
    body={'id':identifier,'sgg':request.sgg,'sex':'M','age_group':'youth','as_of':day.isoformat(),
          'created_at':utcnow().isoformat(),'generator_version':VERSION,'seed':SEED,
          'data_mode':service.settings.data_mode,'llm_mode':service.settings.llm_mode,
          'baseline_input_hash':metadata['input_hash'],'months':months,'inputs':inputs,'signals':signals,
          'input_hash':digest({'inputs':inputs,'signals':signals}),
          'assumptions':['실제 관측과 분리한 합성 미래 시나리오이며 예측 모델의 출력이 아닙니다.',
                         '원천 지수 ±0.06 균등 변형과 가정된 주간 신호 2개를 사용합니다.',
                         '남성·청년 요청 집단의 원천 범위 한계를 유지합니다. 실제 성별 측정치가 아닐 수 있습니다.',
                         '자원은 생성일 현재 목록을 미래 가정에 대입하며 미래 가용성·실제 배정은 미확인입니다.'],
          'periods':[]}
    prepared=[]
    for month in months:
        scenario=Scenario(id='regional-workflow-future',type='monthly',sim_time=f'{month}-01T09:00:00+09:00',
            payload={'workflow_version':'regional-workflow-1','research_gaps':True,'future_input_hash':body['input_hash'],
                     'task':{'future_id':identifier,'sgg':request.sgg,'sex':'M','age_group':'youth','ym':month,'as_of':body['as_of'],
                             'goal':'합성 미래 시나리오를 검토하고 현재 등록 자원과 정책의 조건부 대응 후보를 조사하세요. 실제 예측·미래 가용성·배정으로 주장하지 마세요.'}})
        run=service.new_run(scenario,str(uuid4())).model_copy(update={'status':'pending'})
        prepared.append((run,scenario));body['periods'].append({'ym':month,'run_id':run.id})
    with service.store.connection(write=True) as db:
        existing=db.execute('SELECT body FROM future_batches WHERE id=?',(identifier,)).fetchone()
        if existing:
            previous=json.loads(existing[0])
            if previous['llm_mode']!=service.settings.llm_mode:raise ValueError('restore original LLM mode')
            if previous['sgg']!=request.sgg:raise ValueError('request id already used for another region')
            return previous
        db.execute('INSERT INTO future_batches VALUES (?,?)',(identifier,json.dumps(body,ensure_ascii=False)))
        for run,scenario in prepared:
            db.execute('INSERT INTO runs VALUES (?,?)',(run.id,run.model_dump_json()))
            db.execute('INSERT INTO run_clocks VALUES (?,?,?)',(run.id,service.store.clock_id,time.monotonic()))
            db.execute('INSERT INTO workflows VALUES (?,?)',(run.id,scenario.model_dump_json()))
    return body


def public_batch(service,body):
    result={k:v for k,v in body.items() if k not in ('inputs','signals')}
    result['periods']=[{**p,'status':service.store.get_run(p['run_id']).status} for p in body['periods']]
    result['synthetic']=True
    return result


def execute_batch(service,body):
    for period in body['periods']:
        service.execute(period['run_id'])


def future_router(service):
    with service.store.connection(write=True) as db:
        db.execute('CREATE TABLE IF NOT EXISTS future_batches (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
    router=APIRouter(prefix='/future')
    @router.post('/batches',status_code=202)
    def create(request:FutureRequest,background:BackgroundTasks):
        try:body=create_batch(service,request)
        except (ValueError,OSError):raise HTTPException(422,'실제 기준 자료 또는 요청 범위를 확인하세요.')
        background.add_task(execute_batch,service,body)
        return public_batch(service,body)
    @router.get('/batches/{identifier}')
    def get(identifier:UUID):
        try:return public_batch(service,read_snapshot(service.settings,identifier))
        except (ValueError,sqlite3.Error):raise HTTPException(404,'미래 시나리오를 찾을 수 없습니다.')
    return router
