"""Explicit regeneration preserves the original and shares its call/cost budget."""
import json
from uuid import UUID, uuid5, NAMESPACE_URL
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict
from backend.policy.alternative_review import read


class Regenerate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    version:str
    revision:int


def execute(service,identifier):
    with service.lock('policy-regenerate:'+identifier):
        with service.store.connection() as db:
            job=json.loads(db.execute('SELECT body FROM policy_regenerations WHERE id=?',(identifier,)).fetchone()[0])
        if job['status']=='completed':return
        if job['source']['data_mode']!=service.settings.data_mode or job['source']['llm_mode']!=service.settings.llm_mode:
            job['status']='mode_mismatch'
            with service.store.connection(write=True) as db:db.execute('UPDATE policy_regenerations SET body=? WHERE id=?',(json.dumps(job,ensure_ascii=False),identifier))
            return
        source=job['source'];context=source['evidence']
        context={**context,'regeneration_id':identifier}
        from backend.policy.alternatives import generate
        try:
            generate(service.policy_designer,identifier,job['run_id'],source['scope'],[{'dong_cd':source['dong_cd'],'dong_nm':source['dong_nm']}],[],contexts={source['dong_cd']:context})
            job['status']='completed'
        except Exception as exc:job.update(status='failed',error_type=type(exc).__name__)
        with service.store.connection(write=True) as db:db.execute('UPDATE policy_regenerations SET body=? WHERE id=?',(json.dumps(job,ensure_ascii=False),identifier))


def router(service):
    with service.store.connection() as db:db.execute('CREATE TABLE IF NOT EXISTS policy_regenerations (id TEXT PRIMARY KEY,body TEXT NOT NULL)')
    result=APIRouter(prefix='/policy-proposals')
    @result.post('/{owner_id}/{dong_cd}/regenerate',status_code=202)
    def start(owner_id:UUID,dong_cd:str,request:Regenerate,background:BackgroundTasks):
        identifier=str(request.request_id);intent={'owner_id':str(owner_id),'dong_cd':dong_cd,'version':request.version,'revision':request.revision}
        with service.lock('policy-regenerate:'+identifier),service.store.connection(write=True) as db:
            saved=db.execute('SELECT body FROM policy_regenerations WHERE id=?',(identifier,)).fetchone()
            if saved:
                job=json.loads(saved[0])
                if job['intent']!=intent:raise HTTPException(409,'다른 재생성 요청에 사용된 키입니다.')
            else:
                try:source=read(db,str(owner_id),dong_cd)
                except KeyError:raise HTTPException(404,'정책 대안 없음')
                if source['version']!=request.version or source['review_revision']!=request.revision:raise HTTPException(409,'최신 검토 버전을 불러오세요.')
                if source['data_mode']!=service.settings.data_mode or source['llm_mode']!=service.settings.llm_mode:raise HTTPException(409,'원래 실행 모드를 복원하세요.')
                parent=db.execute('SELECT body FROM policy_regenerations WHERE id=?',(str(owner_id),)).fetchone()
                run_id=json.loads(parent[0])['run_id'] if parent else str(uuid5(NAMESPACE_URL,'policy-batch:'+str(owner_id))) if db.execute('SELECT 1 FROM regional_batches WHERE id=?',(str(owner_id),)).fetchone() else str(owner_id)
                job={'id':identifier,'status':'pending','intent':intent,'source':source,'run_id':run_id}
                db.execute('INSERT INTO policy_regenerations VALUES (?,?)',(identifier,json.dumps(job,ensure_ascii=False)))
        if job['status']!='completed':background.add_task(execute,service,identifier)
        return {'id':identifier,'status':job['status']}
    @result.get('/regenerations/{identifier}')
    def get(identifier:UUID):
        with service.store.connection() as db:row=db.execute('SELECT body FROM policy_regenerations WHERE id=?',(str(identifier),)).fetchone()
        if not row:raise HTTPException(404,'재생성 요청 없음')
        job=json.loads(row[0]);return {'id':job['id'],'status':job['status'],'source_owner':job['intent']['owner_id']}
    return result


def recover(service):
    with service.store.connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='policy_regenerations'").fetchone():return
        identifiers=[r[0] for r in db.execute("SELECT id FROM policy_regenerations WHERE json_extract(body,'$.status') IN ('pending','mode_mismatch')")]
    for identifier in identifiers:execute(service,identifier)
