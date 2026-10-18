import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import socket
import sqlite3
import threading
import time

import httpx
import pytest
import uvicorn

from backend.app.config import Settings
from backend.app.contracts import Alert, Run
from backend.app.main import create_app
from backend.events import EventStore, utcnow

SIM = '2025-07-01T09:00:00+09:00'


def run(store, run_id='r'):
    return store.create_run(Run(id=run_id, scenario_id='s-' + run_id, thread_id=run_id,
        status='running', data_mode='sample', llm_mode='fake', input_version='1', rule_version='1',
        model_version='fake', prompt_version='1', catalog_version='synthetic-1', started_at=utcnow()))


def alert(store, alert_id='a', run_id='r'):
    return store.create_alert(Alert(id=alert_id, run_id=run_id, type='crisis', status='created', created_at=utcnow()), SIM)


def test_concurrent_sequences_and_restart_isolation(tmp_path):
    store = EventStore(tmp_path / 'events.sqlite3')
    run(store)
    run(store, 'other')
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda i: store.append_trace('r', SIM, 'node_start', {'i': i}), range(30)))
    store.append_trace('other', SIM, 'node_start', {})
    recovered = EventStore(store.path)
    assert [t['seq'] for t in recovered.traces('r')] == list(range(1, 31))
    assert all(t['scenario_id'] == 's-r' and t['wall_ts'].endswith('Z') for t in recovered.traces('r'))
    assert len(recovered.traces('other')) == 1
    assert [t['seq'] for t in recovered.traces('r', 28)] == [29, 30]


def test_alert_receipt_identity_idempotency_and_atomicity(tmp_path, monkeypatch):
    store = EventStore(tmp_path / 'events.sqlite3')
    run(store)
    alert(store)
    browser_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first = store.receipt('a', 'one', browser_time, SIM)
    assert store.receipt('a', 'one', utcnow(), SIM) == first
    store.receipt('a', 'two', utcnow(), SIM)
    assert len([t for t in store.traces('r') if t['kind'] == 'received']) == 2
    with pytest.raises(ValueError, match='this client'):
        store.acknowledge('a', 'three', 'operator', SIM)
    confirmed = store.acknowledge('a', 'one', 'operator', SIM)
    assert store.acknowledge('a', 'two', 'operator', SIM) == confirmed
    assert len([t for t in store.traces('r') if t['kind'] == 'acknowledged']) == 1
    assert first['server_received_at'] != first['browser_received_at']
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('injected failure')
    monkeypatch.setattr(store, '_trace', fail)
    with pytest.raises(sqlite3.OperationalError):
        alert(store, 'failed')
    assert [a['id'] for a in store.alerts()] == ['a']


@pytest.fixture
def server(tmp_path, monkeypatch):
    import backend.app.config as config
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    app = create_app(Settings(_env_file=None, data_mode='sample', llm_mode='fake'))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    service = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=service.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if service.started:
            break
        time.sleep(.02)
    assert service.started
    try:
        yield app.state.store, f'http://127.0.0.1:{port}'
    finally:
        service.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


def next_event(lines):
    for line in lines:
        if line.startswith('data: '):
            return json.loads(line[6:])
    raise AssertionError('stream closed before event')


def test_real_http_sse_replay_two_subscribers_and_ack(server):
    store, url = server
    run(store)
    run(store, 'second')
    alert(store)
    alert(store, 'b', 'second')
    with httpx.Client(base_url=url, timeout=3) as one, httpx.Client(base_url=url, timeout=3) as two:
        with one.stream('GET', '/alerts/stream') as first, two.stream('GET', '/alerts/stream') as second:
            first_lines, second_lines = first.iter_lines(), second.iter_lines()
            assert next_event(first_lines)['id'] == 'a'
            assert next_event(second_lines)['id'] == 'a'
            # Leave the second subscriber idle; commits and the other subscriber still progress.
            alert(store, 'c')
            assert next_event(first_lines)['id'] == 'b'
            assert next_event(first_lines)['id'] == 'c'
        with one.stream('GET', '/alerts/stream', headers={'Last-Event-ID': '2'}) as reconnected:
            assert next_event(reconnected.iter_lines())['id'] == 'c'
        with one.stream('GET', '/runs/r/traces/stream', headers={'Last-Event-ID': '1'}) as traces:
            trace = next_event(traces.iter_lines())
            assert trace['run_id'] == 'r' and trace['seq'] == 2
        assert one.get('/alerts/stream', headers={'Last-Event-ID': '-1'}).status_code == 422
        assert one.get('/runs/missing/traces/stream').status_code == 404
        receipt = {'client_id': 'one', 'browser_received_at': '2025-07-01T00:00:00Z', 'sim_ts': SIM}
        response = one.post('/alerts/a/receipt', json=receipt)
        assert response.status_code == 200
        assert one.post('/alerts/a/receipt', json=receipt).json() == response.json()
        assert one.post('/alerts/a/acknowledge', json={'client_id': 'one', 'operator': 'test', 'sim_ts': SIM}).status_code == 200
        assert one.get('/health').status_code == 200


def test_stream_heartbeat_and_disconnect(monkeypatch):
    from backend.app import event_routes
    class Request:
        async def is_disconnected(self):
            return False
    ticks = iter([0, 16, 16])
    from types import SimpleNamespace
    monkeypatch.setattr(event_routes, 'time', SimpleNamespace(monotonic=lambda: next(ticks, 16)))
    async def check():
        events = event_routes.stream(Request(), lambda a, n: [], 0, 'seq', 'trace')
        assert await anext(events) == ': heartbeat\n\n'
        await events.aclose()
    asyncio.run(check())


def test_receipt_duration_is_unknown_after_restart(tmp_path):
    store = EventStore(tmp_path / 'events.sqlite3')
    run(store)
    alert(store)
    first = store.receipt('a', 'one', utcnow(), SIM)
    assert first['run_to_receipt_ms'] >= 0
    restarted = EventStore(store.path)
    second = restarted.receipt('a', 'two', utcnow(), SIM)
    assert second['run_to_receipt_ms'] is None
    assert second['clock_id'] != first['clock_id']


def test_event_creation_is_internal_and_mode_boundary(server):
    store, url = server
    created = run(store)
    with pytest.raises(ValueError, match='data mode'):
        store.create_run(created.model_copy(update={'id': 'local', 'data_mode': 'local'}))
    with httpx.Client(base_url=url) as client:
        assert client.post('/runs', json=created.model_dump(mode='json')).status_code == 405
        assert client.post('/runs/r/alerts', json={'type': 'linkage_completed', 'sim_ts': SIM}).status_code == 404


def test_graph_http_approval_and_health_during_work(server, monkeypatch):
    from backend.graph import GraphService
    store, url = server
    entered, release = threading.Event(), threading.Event()
    original = GraphService.classify_node
    def slow(self, state):
        entered.set()
        assert release.wait(timeout=5)
        return original(self, state)
    monkeypatch.setattr(GraphService, 'classify_node', slow)
    with ThreadPoolExecutor(max_workers=1) as pool, httpx.Client(base_url=url, timeout=5) as client:
        future = pool.submit(httpx.post, url + '/scenarios/run', json={
            'id': 'slow', 'type': 'case', 'sim_time': SIM, 'payload': {'text': '상담 요청'}}, timeout=5)
        try:
            assert entered.wait(timeout=3)
            assert client.get('/health', timeout=1).status_code == 200
        finally:
            release.set()
        response = future.result()
        assert response.status_code == 201
        run_id = response.json()['id']
        assert client.get(f'/runs/{run_id}/linkage').status_code == 404
        approval = client.get(f'/runs/{run_id}/approval').json()['approval']
        decision = {'snapshot_version': approval['snapshot_version'], 'status': 'approved', 'operator': 'test'}
        assert client.post(f'/runs/{run_id}/decision', json={**decision, 'snapshot_version': 'wrong'}).status_code == 409
        assert client.post(f'/runs/{run_id}/decision', json=decision).json()['status'] == 'completed'
        assert client.get(f'/runs/{run_id}/linkage').status_code == 200
