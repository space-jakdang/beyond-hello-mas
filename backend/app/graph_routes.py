from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import ValidationError, Field
from backend.app.contracts import Contract, Nonempty, Scenario


class DecisionInput(Contract):
    snapshot_version: Nonempty
    status: Literal['approved', 'rejected']
    operator: Nonempty
    reason: Nonempty | None = None


class RevisionInput(Contract):
    snapshot_version: Nonempty
    operator: Nonempty
    reason: Nonempty = Field(max_length=1000)


def graph_router(service):
    router = APIRouter()

    @router.post('/scenarios/run', status_code=202)
    def start(body: Scenario, background: BackgroundTasks):
        try:
            run = service.register(body)
            background.add_task(service.execute, run.id)
            return run
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(422, str(exc))

    @router.get('/runs/{run_id}/overview')
    def overview(run_id: str):
        try:
            run = service.store.get_run(run_id)
        except KeyError:
            raise HTTPException(404, 'run not found')
        traces = service.store.traces(run_id, limit=1000)
        classification = next((t['payload'] for t in traces if t['agent'] == 'classify' and t['kind'] == 'node_end'), None)
        try:
            proposal = service.approval(run_id)
        except KeyError:
            proposal = None
        policy = next((t['payload'] for t in traces if t['agent'] == 'policy' and t['kind'] == 'node_end'), None)
        with service.store.connection() as db:
            parent=db.execute('SELECT parent_run_id FROM revisions WHERE child_run_id=?',(run_id,)).fetchone()
            child=db.execute('SELECT child_run_id FROM revisions WHERE parent_run_id=?',(run_id,)).fetchone()
        return {'revision':{'parent_run_id':parent[0] if parent else None,'child_run_id':child[0] if child else None},'run': run, 'policy': policy, 'classification': classification, 'review': proposal, 'traces': traces}

    @router.get('/runs/{run_id}/approval')
    def approval(run_id: str):
        try:
            return service.approval(run_id)
        except KeyError:
            raise HTTPException(404, 'approval not found')

    @router.post('/runs/{run_id}/decision')
    def decide(run_id: str, body: DecisionInput):
        try:
            return service.decide(run_id, body.snapshot_version, body.status, body.operator, body.reason)
        except KeyError:
            raise HTTPException(404, 'approval not found')
        except (ValueError, ValidationError) as exc:
            raise HTTPException(409, str(exc))

    @router.post('/runs/{run_id}/revision',status_code=202)
    def revise(run_id:str,body:RevisionInput,background:BackgroundTasks):
        from backend.revisions import request_revision
        try:
            child=request_revision(service,run_id,body.snapshot_version,body.operator,body.reason)
            background.add_task(service.execute,child.id)
            return child
        except KeyError:
            raise HTTPException(404,'approval not found')
        except ValueError as exc:
            raise HTTPException(409,str(exc))

    @router.get('/runs/{run_id}/linkage')
    def linkage(run_id: str):
        import json
        with service.store.connection() as db:
            row = db.execute('SELECT body FROM linkages WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'linkage not found')
        return json.loads(row['body'])

    return router
