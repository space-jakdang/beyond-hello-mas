"""Revision-checked policy review. Review never authorizes an allocation."""
import json
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from backend.events import utcnow


def initialize(store):
    with store.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS policy_alternative_revisions (owner_id TEXT,dong_cd TEXT,revision INTEGER,body TEXT NOT NULL,PRIMARY KEY(owner_id,dong_cd,revision))')


def read(db,owner,dong,revision=None):
    if revision is None:row=db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=? AND dong_cd=?',(owner,dong)).fetchone()
    else:
        row=db.execute('SELECT body FROM policy_alternative_revisions WHERE owner_id=? AND dong_cd=? AND revision=?',(owner,dong,revision)).fetchone()
        if not row:
            current=read(db,owner,dong)
            if current['review_revision']==revision:return current
    if not row:raise KeyError('proposal revision missing')
    return json.loads(row[0])


class Change(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    version:str
    revision:int=Field(ge=0)
    alternative_id:UUID
    operator:str=Field(min_length=1,max_length=100)
    action:Literal['edit','approve','reject']
    text:str=Field(min_length=1,max_length=2000)


def update(store,owner,dong,change):
    with store.connection(write=True) as db:
        body=read(db,owner,dong)
        if body['version']!=change.version or body['review_revision']!=change.revision:raise ValueError('revision conflict')
        item=next((a for a in body['alternatives'] if a['id']==str(change.alternative_id)),None)
        if not item:raise KeyError('alternative missing')
        db.execute('INSERT OR IGNORE INTO policy_alternative_revisions VALUES (?,?,?,?)',(owner,dong,body['review_revision'],json.dumps(body,ensure_ascii=False)))
        if change.action=='edit':
            item['operator_notes']=change.text
            for alternative in body['alternatives']:
                alternative['review_status']='pending';alternative.pop('review',None)
        else:
            item['review_status']='approved' if change.action=='approve' else 'rejected'
            item['review']={'operator':change.operator,'reason':change.text,'at':utcnow().isoformat()}
        body['review_revision']+=1
        body.setdefault('history',[]).append({'revision':body['review_revision'],'alternative_id':str(change.alternative_id),
            'action':change.action,'operator':change.operator,'text':change.text,'at':utcnow().isoformat()})
        encoded=json.dumps(body,ensure_ascii=False)
        db.execute('INSERT INTO policy_alternative_revisions VALUES (?,?,?,?)',(owner,dong,body['review_revision'],encoded))
        db.execute('UPDATE policy_alternative_sets SET body=? WHERE owner_id=? AND dong_cd=?',(encoded,owner,dong))
    return body


def router(store):
    initialize(store)
    result=APIRouter(prefix='/policy-proposals')
    @result.post('/{owner_id}/{dong_cd}/review')
    def review(owner_id:UUID,dong_cd:str,change:Change):
        try:return update(store,str(owner_id),dong_cd,change)
        except KeyError:raise HTTPException(404,'정책 대안 없음')
        except ValueError:raise HTTPException(409,'다른 검토가 저장되었습니다. 최신 내용을 불러오세요.')
    @result.get('/{owner_id}/{dong_cd}/revisions/{revision}')
    def revision(owner_id:UUID,dong_cd:str,revision:int):
        try:
            with store.connection() as db:return read(db,str(owner_id),dong_cd,revision)
        except KeyError:raise HTTPException(404,'검토 버전 없음')
    return result
