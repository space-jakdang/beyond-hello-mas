"""Frozen, idempotent batches of existing single-cohort regional workflows."""
import json
import time
from uuid import UUID, uuid4
from datetime import date
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, model_validator
from backend.app.contracts import Scenario
from backend.tools.regional_task import RegionalTask, assess
from backend.tools.segments_v3 import load_segments
from backend.tools.indicators import digest
from backend.tools.catalog import load_catalog
from backend.events import utcnow

class BatchConflict(ValueError):
    pass


class BatchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    task:dict
    workflow_version:Literal['regional-workflow-1','regional-workflow-2']='regional-workflow-1'
    sex:Literal['all','M','F']='all'
    age_group:Literal['all','youth','midlife','prime','elderly']='all'
    source_age_band:str='all'
    week:date | Literal['all']='all'
    card_age:Literal['all','20s','30s']='all'

    @model_validator(mode='after')
    def versioned_scope(self):
        if self.workflow_version=='regional-workflow-1' and self.source_age_band!='all':
            raise ValueError('source age band requires regional-workflow-2')
        if self.workflow_version=='regional-workflow-2' and (self.age_group!='all' or self.week!='all' or self.card_age!='all'):
            raise ValueError('v4 batch uses source_age_band and task.card_week')
        return self


def initialize(store):
    with store.connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS regional_batches (id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS regional_batch_children (
            run_id TEXT PRIMARY KEY REFERENCES runs(id), batch_id TEXT NOT NULL REFERENCES regional_batches(id),
            assessment TEXT NOT NULL);
        ''')


def read(service,identifier):
    with service.store.connection() as db:
        row=db.execute('SELECT body FROM regional_batches WHERE id=?',(str(identifier),)).fetchone()
    if not row:raise KeyError(identifier)
    body=json.loads(row[0])
    if body['data_mode']!=service.settings.data_mode or body['llm_mode']!=service.settings.llm_mode:
        raise BatchConflict('restore original data and model mode')
    return body


def create(service,request):
    identifier=str(request.request_id);intent=request.model_dump(mode='json',exclude={'request_id'})
    if request.workflow_version=='regional-workflow-1':
        intent.pop('workflow_version',None);intent.pop('source_age_band',None)
    try:
        existing=read(service,identifier)
        if existing['intent']!=intent:raise BatchConflict('request id used for a different selection')
        return existing
    except KeyError:pass
    if request.workflow_version=='regional-workflow-2':
        return create_v4(service,request,identifier,intent)
    task=RegionalTask.model_validate({**request.task,'sex':'M','age_group':'youth'})
    if task.future_id:raise ValueError('use future workflow for synthetic inputs')
    rows,source=load_segments(service.settings)
    region=[r for r in rows if r.sgg==task.sgg]
    dongs={r.dong_cd:r.dong_nm for r in region}
    if not dongs or task.dong_cd and task.dong_cd not in dongs:raise ValueError('unknown region or dong')
    body={'id':identifier,'intent':intent,'data_mode':service.settings.data_mode,'llm_mode':service.settings.llm_mode,
          'task':task.model_dump(mode='json'),'source':source,'children':[],'cancelled':False,'policy_proposal_version':'three-1',
          'dongs':[{'dong_cd':k,'dong_nm':v} for k,v in sorted(dongs.items()) if not task.dong_cd or k==task.dong_cd]}
    prepared=[]
    catalog=[r.model_dump(mode="json") for r in load_catalog(service.settings.catalog_path)]
    for sex in (['M','F'] if request.sex=='all' else [request.sex]):
        for age in (['youth','midlife','prime','elderly'] if request.age_group=='all' else [request.age_group]):
            single=task.model_copy(update={'sex':sex,'age_group':age})
            available=[r for r in region if r.preferred and r.sex==sex and r.age_group==age and r.ym in (None,task.ym) and (not task.dong_cd or r.dong_cd==task.dong_cd)]
            if not available:
                body['children'].append({'sex':sex,'age_group':age,'run_id':None,'status':'no_observation'});continue
            assessment=assess(service.settings,single,source_data=(rows,source))
            assessment['catalog_snapshot']=catalog
            scenario=Scenario(id='regional-workflow-batch',type='monthly',sim_time=f'{task.ym}-01T09:00:00+09:00',
                              payload={'statistics_version':'2','workflow_version':'regional-workflow-1','research_gaps':True,'policy_proposal_version':'batch-child','task':single.model_dump(mode='json')})
            run=service.new_run(scenario,str(uuid4())).model_copy(update={'status':'pending'})
            prepared.append((run,scenario,assessment))
            body['children'].append({'sex':sex,'age_group':age,'run_id':run.id})
    body['input_hash']=digest([a for _,_,a in prepared])
    with service.store.connection(write=True) as db:
        previous=db.execute('SELECT body FROM regional_batches WHERE id=?',(identifier,)).fetchone()
        if previous:
            result=json.loads(previous[0])
            if result['intent']!=intent:raise BatchConflict('request conflict')
            return result
        db.execute('INSERT INTO regional_batches VALUES (?,?)',(identifier,json.dumps(body,ensure_ascii=False)))
        for run,scenario,assessment in prepared:
            db.execute('INSERT INTO runs VALUES (?,?)',(run.id,run.model_dump_json()))
            db.execute('INSERT INTO run_clocks VALUES (?,?,?)',(run.id,service.store.clock_id,time.monotonic()))
            db.execute('INSERT INTO workflows VALUES (?,?)',(run.id,scenario.model_dump_json()))
            db.execute('INSERT INTO regional_batch_children VALUES (?,?,?)',(run.id,identifier,json.dumps(assessment,ensure_ascii=False)))
    return body


def create_v4(service,request,identifier,intent):
    from backend.tools.neighborhoods import group_analysis_v4
    from backend.tools.regional_task_v4 import RegionalTaskV4, VERSION
    from backend.tools.segments_v4 import SOURCE_AGE_BANDS

    region='강남' if request.task.get('sgg')=='11230' else '춘천' if request.task.get('sgg')=='32010' else None
    if region is None:raise ValueError('unknown region')
    bands=SOURCE_AGE_BANDS[region]
    selected=request.source_age_band
    if selected=='all' and request.task.get('source_age_band'):
        selected=request.task['source_age_band']
    ages=list(bands) if selected=='all' else [selected]
    if any(age not in bands for age in ages):raise ValueError('source age outside region')
    base_band=ages[0]
    task_base=RegionalTaskV4.model_validate({**{k:v for k,v in request.task.items() if k!='source_age_band'},
                                             'sex':'M','source_age_band':base_band})
    data=group_analysis_v4(service.settings,task_base.card_week)
    region_rows=[row for row in data['segments'] if row['sgg']==task_base.sgg
                 and (not task_base.dong_cd or row['dong_cd']==task_base.dong_cd)]
    if not region_rows:raise ValueError('unknown region or dong')
    dongs={row['dong_cd']:row['dong_nm'] for row in region_rows}
    source={'dataset_version':data['metadata']['dataset_version'],'input_hash':data['metadata']['input_hash'],
            'selected_week':data['metadata']['selected_week']}
    body_task={**task_base.model_dump(mode='json'),'source_age_band':selected,
               'age_group':selected,'ym':task_base.card_week.strftime('%Y-%m')}
    body={'id':identifier,'intent':intent,'data_mode':service.settings.data_mode,'llm_mode':service.settings.llm_mode,
          'workflow_version':VERSION,'task':body_task,'source':source,'children':[],'cancelled':False,
          'policy_proposal_version':'three-1',
          'dongs':[{'dong_cd':code,'dong_nm':name} for code,name in sorted(dongs.items())]}
    prepared=[]
    catalog=[row.model_dump(mode='json') for row in load_catalog(service.settings.catalog_path)]
    sexes=['M','F'] if request.sex=='all' else [request.sex]
    for sex in sexes:
        for age in ages:
            single=RegionalTaskV4.model_validate({**task_base.model_dump(mode='json'),'sex':sex,'source_age_band':age})
            available=[row for row in region_rows if row['sex']==sex and row['source_age_band']==age]
            if not available:
                body['children'].append({'sex':sex,'age_group':age,'source_age_band':age,'run_id':None,'status':'no_observation'})
                continue
            assessment=assess(service.settings,single,source_data=data)
            assessment['catalog_snapshot']=catalog
            scenario=Scenario(id='regional-workflow-batch-v4',type='monthly',
                sim_time=f'{single.as_of.isoformat()}T09:00:00+09:00',
                payload={'statistics_version':'3','workflow_version':VERSION,'research_gaps':True,
                         'policy_proposal_version':'batch-child','task':single.model_dump(mode='json')})
            run=service.new_run(scenario,str(uuid4())).model_copy(update={'status':'pending'})
            prepared.append((run,scenario,assessment))
            body['children'].append({'sex':sex,'age_group':age,'source_age_band':age,'run_id':run.id})
    body['input_hash']=digest([assessment for _,_,assessment in prepared])
    with service.store.connection(write=True) as db:
        previous=db.execute('SELECT body FROM regional_batches WHERE id=?',(identifier,)).fetchone()
        if previous:
            result=json.loads(previous[0])
            if result['intent']!=intent:raise BatchConflict('request conflict')
            return result
        db.execute('INSERT INTO regional_batches VALUES (?,?)',(identifier,json.dumps(body,ensure_ascii=False)))
        for run,scenario,assessment in prepared:
            db.execute('INSERT INTO runs VALUES (?,?)',(run.id,run.model_dump_json()))
            db.execute('INSERT INTO run_clocks VALUES (?,?,?)',(run.id,service.store.clock_id,time.monotonic()))
            db.execute('INSERT INTO workflows VALUES (?,?)',(run.id,scenario.model_dump_json()))
            db.execute('INSERT INTO regional_batch_children VALUES (?,?,?)',(run.id,identifier,json.dumps(assessment,ensure_ascii=False)))
    return body


def public(service,body):
    children=[{**c,'status':service.store.get_run(c['run_id']).status if c['run_id'] else 'no_observation'} for c in body['children']]
    pending=sum(c['status'] in ('pending','running') for c in children)
    return {**body,'children':children,'status':('cancelling' if any(c['status']=='running' for c in children) else 'cancelled') if body['cancelled'] else 'running' if pending or body.get('policy_proposal_version') and not body.get('policy_proposals') else 'completed_with_fallback' if body.get('policy_proposals',{}).get('fallback_count') else 'completed_with_gaps' if any(c['status'] in ('failed','no_observation') for c in children) else 'completed',
            'finished':len(children)-pending,'total':len(children),'failed_count':sum(c['status']=='failed' for c in children),'no_observation_count':sum(c['status']=='no_observation' for c in children)}


def execute(service,identifier):
    with service.lock('batch:'+str(identifier)):
        body=read(service,identifier)
        for child in body['children']:
            if read(service,identifier)['cancelled']:break
            if child['run_id'] and service.store.get_run(child['run_id']).status in ('pending','running'):
                try:service.execute(child['run_id'])
                except Exception:pass  # Graph persists the failure; continue the other cohorts.
        from backend.policy.alternatives import complete_batch
        if body.get('policy_proposal_version'):complete_batch(service,body)


def router(service):
    result=APIRouter(prefix='/regional/batches')
    @result.post('',status_code=202)
    def start(request:BatchRequest,background:BackgroundTasks):
        try:
            with service.lock('batch:'+str(request.request_id)):body=create(service,request)
        except BatchConflict:raise HTTPException(409,'요청 키가 다른 선택에 사용되었거나 실행 모드가 다릅니다.')
        except (ValueError,OSError):raise HTTPException(422,'집단 범위·자료·요청 키를 확인하세요.')
        background.add_task(execute,service,body['id']);return public(service,body)
    @result.get('/{identifier}')
    def get(identifier:UUID):
        try:return public(service,read(service,identifier))
        except KeyError:raise HTTPException(404,'업무 없음')
        except ValueError:raise HTTPException(409,'원래 실행 모드를 복원하세요.')
    @result.post('/{identifier}/resume',status_code=202)
    def resume(identifier:UUID,background:BackgroundTasks):
        try:body=read(service,identifier)
        except KeyError:raise HTTPException(404,'업무 없음')
        except ValueError:raise HTTPException(409,'원래 실행 모드를 복원하세요.')
        if body['cancelled']:raise HTTPException(409,'취소된 업무는 새 요청으로 실행하세요.')
        background.add_task(execute,service,str(identifier));return public(service,body)
    @result.post('/{identifier}/cancel')
    def cancel(identifier:UUID):
        try:read(service,identifier)
        except KeyError:raise HTTPException(404,'업무 없음')
        except ValueError:raise HTTPException(409,'원래 실행 모드를 복원하세요.')
        with service.store.connection(write=True) as db:
            row=db.execute('SELECT body FROM regional_batches WHERE id=?',(str(identifier),)).fetchone()
            body=json.loads(row[0]);body['cancelled']=True
            for child in body['children']:
                if child['run_id']:
                    run=db.execute('SELECT body FROM runs WHERE id=?',(child['run_id'],)).fetchone()
                    if json.loads(run[0])['status']=='pending':service.update_run(db,child['run_id'],status='cancelled',ended_at=utcnow())
            db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),str(identifier)))
        return public(service,body)
    return result
