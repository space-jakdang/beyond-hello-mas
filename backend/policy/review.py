"""Append-only human review of policy drafts, separate from resource approval."""
import json
from typing import Literal
from pydantic import Field
from fastapi import APIRouter,HTTPException
from backend.policy.design_contracts import Contract,PolicyDraft,validate_draft
from backend.tools.indicators import digest
from backend.events import utcnow


class ReviewInput(Contract):
    expected_revision:int=Field(ge=0)
    version:str=Field(min_length=1)
    action:Literal['approved','rejected','needs_revision','revise']
    operator:str=Field(min_length=1,max_length=100)
    reason:str=Field(min_length=1,max_length=1000)
    draft:PolicyDraft|None=None


class PolicyReview:
    def __init__(self,store):
        self.store=store
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS policy_design_history (run_id TEXT NOT NULL REFERENCES runs(id), revision INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(run_id,revision))')

    def read(self,db,run_id):
        row=db.execute('SELECT body FROM policy_designs WHERE run_id=?',(run_id,)).fetchone()
        if row is None:raise KeyError(run_id)
        original=json.loads(row[0])
        history=[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_design_history WHERE run_id=? ORDER BY revision',(run_id,))]
        return {'run_id':run_id,'revision':len(history),'document':history[-1]['document'] if history else original,'history':history}

    def get(self,run_id):
        with self.store.connection() as db:return self.read(db,run_id)

    def act(self,run_id,body):
        body=ReviewInput.model_validate(body);request_hash=digest(body.model_dump())
        with self.store.connection(write=True) as db:
            current=self.read(db,run_id);document=current['document'];history=current['history']
            if any(entry['request_hash']==request_hash for entry in history):return current
            if body.expected_revision!=current['revision'] or body.version!=document.get('version'):
                raise ValueError('policy draft changed; reload before review')
            if not document.get('draft'):raise ValueError('no reviewable policy draft')
            if body.action=='revise':
                if body.draft is None:raise ValueError('revision requires draft')
                checked=validate_draft(body.draft.model_dump(),document.get('considered_evidence_ids') or document['draft']['problem_evidence_ids'],document['gap'],document['analogues'])
                if checked['version']==document['version']:raise ValueError('revision must change draft')
                document={**document,**checked,'status':checked['draft']['status']}
            else:
                if body.draft is not None:raise ValueError('review cannot replace draft')
                if document.get('review_status')!='pending':raise ValueError('draft already reviewed; create a revision')
                if body.action=='approved' and document['draft']['status']!='draft':raise ValueError('insufficient evidence cannot be approved')
                document={**document,'review_status':body.action}
            revision=current['revision']+1
            entry={'revision':revision,'at':utcnow().isoformat(),'action':body.action,'operator':body.operator,'reason':body.reason,
                   'request_hash':request_hash,'document':document}
            db.execute('INSERT INTO policy_design_history VALUES (?,?,?)',(run_id,revision,json.dumps(entry,ensure_ascii=False)))
            return {'run_id':run_id,'revision':revision,'document':document,'history':history+[entry]}


def policy_review_router(store):
    router=APIRouter();review=PolicyReview(store)
    @router.get('/runs/{run_id}/policy-design')
    def get(run_id:str):
        try:return review.get(run_id)
        except KeyError:raise HTTPException(404,'policy design not found')
    @router.post('/runs/{run_id}/policy-design/review')
    def act(run_id:str,body:ReviewInput):
        try:return review.act(run_id,body)
        except KeyError:raise HTTPException(404,'policy design not found')
        except ValueError as exc:raise HTTPException(409,str(exc))
    return router
