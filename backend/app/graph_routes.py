from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from backend.app.contracts import Contract, Nonempty, Scenario


class DecisionInput(Contract):
    snapshot_version: Nonempty
    status: Literal['approved', 'rejected']
    operator: Nonempty
    reason: Nonempty | None = None


def graph_router(service):
    router = APIRouter()

    @router.post('/scenarios/run', status_code=201)
    def start(body: Scenario):
        try:
            return service.start(body)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(422, str(exc))

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

    @router.get('/runs/{run_id}/linkage')
    def linkage(run_id: str):
        import json
        with service.store.connection() as db:
            row = db.execute('SELECT body FROM linkages WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'linkage not found')
        return json.loads(row['body'])

    return router
