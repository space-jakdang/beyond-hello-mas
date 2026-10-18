import asyncio
import json
import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.app.contracts import Contract, Nonempty, SimTime, WallTime


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
    yield ': connected\n\n'
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
               limit: Annotated[int, Query(ge=1, le=1000)] = 100, recent: bool = False):
        return store.alerts(after, limit, recent)

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
