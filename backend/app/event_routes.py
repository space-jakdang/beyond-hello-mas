import asyncio
import json
import time
import sqlite3
from uuid import uuid4
from typing import Literal
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.app.contracts import Alert, Contract, Nonempty, Run, SimTime, WallTime
from backend.events import utcnow


class AlertInput(Contract):
    type: Literal['crisis', 'approval_requested', 'linkage_completed']
    approval_id: Nonempty | None = None
    sim_ts: SimTime


class ReceiptInput(Contract):
    client_id: Nonempty
    browser_received_at: WallTime
    sim_ts: SimTime


class AcknowledgeInput(Contract):
    client_id: Nonempty
    operator: Nonempty
    sim_ts: SimTime


def cursor(after, last_event_id):
    if last_event_id is None:
        return after
    try:
        value = int(last_event_id)
        if value < 0:
            raise ValueError()
        return value
    except ValueError:
        raise HTTPException(422, 'Last-Event-ID must be a nonnegative integer')


async def stream(request, fetch, after, id_key, event_name):
    heartbeat = time.monotonic()
    while not await request.is_disconnected():
        rows = await asyncio.to_thread(fetch, after, 100)
        for row in rows:
            after = row[id_key]
            yield f'id: {after}\nevent: {event_name}\ndata: {json.dumps(row, ensure_ascii=False)}\n\n'
        if time.monotonic() - heartbeat >= 15:
            yield ': heartbeat\n\n'
            heartbeat = time.monotonic()
        if not rows:
            await asyncio.sleep(0.2)


def event_router(store):
    router = APIRouter()

    def require_run(run_id):
        try:
            return store.get_run(run_id)
        except KeyError:
            raise HTTPException(404, 'run not found')

    @router.post('/runs', status_code=201)
    def register_run(body: Run):
        try:
            return store.create_run(body)
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'run already exists')
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @router.post('/runs/{run_id}/alerts', status_code=201)
    def create_alert(run_id: str, body: AlertInput):
        require_run(run_id)
        if body.type == 'approval_requested' and body.approval_id is None:
            raise HTTPException(422, 'approval request requires approval_id')
        return store.create_alert(Alert(id=str(uuid4()), run_id=run_id, type=body.type,
                                       approval_id=body.approval_id, status='created', created_at=utcnow()), body.sim_ts)

    @router.get('/runs')
    def runs(limit: Annotated[int, Query(ge=1, le=1000)] = 100):
        return store.list_runs(limit)

    @router.get('/runs/{run_id}')
    def run(run_id: str):
        return require_run(run_id)

    @router.get('/runs/{run_id}/traces')
    def traces(run_id: str, after: Annotated[int, Query(ge=0)] = 0,
               limit: Annotated[int, Query(ge=1, le=1000)] = 100):
        require_run(run_id)
        return store.traces(run_id, after, limit)

    @router.get('/runs/{run_id}/traces/stream')
    async def trace_stream(request: Request, run_id: str, after: Annotated[int, Query(ge=0)] = 0,
                           last_event_id: Annotated[str | None, Header()] = None):
        await asyncio.to_thread(require_run, run_id)
        return StreamingResponse(stream(request, lambda a, n: store.traces(run_id, a, n),
                                        cursor(after, last_event_id), 'seq', 'trace'),
                                 media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @router.get('/alerts')
    def alerts(after: Annotated[int, Query(ge=0)] = 0,
               limit: Annotated[int, Query(ge=1, le=1000)] = 100):
        return store.alerts(after, limit)

    @router.get('/alerts/stream')
    async def alert_stream(request: Request, after: Annotated[int, Query(ge=0)] = 0,
                           last_event_id: Annotated[str | None, Header()] = None):
        return StreamingResponse(stream(request, store.alerts, cursor(after, last_event_id), 'cursor', 'alert'),
                                 media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @router.post('/alerts/{alert_id}/receipt')
    def receipt(alert_id: str, body: ReceiptInput):
        try:
            return store.receipt(alert_id, body.client_id, body.browser_received_at, body.sim_ts)
        except KeyError:
            raise HTTPException(404, 'alert not found')

    @router.post('/alerts/{alert_id}/acknowledge')
    def acknowledge(alert_id: str, body: AcknowledgeInput):
        try:
            return store.acknowledge(alert_id, body.client_id, body.operator, body.sim_ts)
        except KeyError:
            raise HTTPException(404, 'alert not found')
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    return router
