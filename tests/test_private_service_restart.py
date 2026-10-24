"""Exercise the actual entrypoint with generated local-format inputs, never private data."""
from contextlib import contextmanager
import os
import socket
import subprocess
import sys
import time

import httpx

from backend.app.config import ROOT
from scripts.runtime_package import build, verify
from tests.test_runtime_package import source, PROVENANCE


@contextmanager
def server(inputs, state, log):
    env = {**os.environ, 'DATA_MODE':'local', 'RESOURCE_CATALOG':'v3', 'LLM_MODE':'fake',
           'INPUT_ROOT':str(inputs), 'RUNTIME_STORAGE_ROOT':str(state), 'EVALUATION_ID':'',
           'OPENAI_API_KEY':'', 'GOV24_API_KEY':'', 'GOV24_SERVICE_KEY':'',
           'PYTHONUNBUFFERED':'1', 'PERSON_MCP_MODE':'stub', 'MCP_ALLOW_FALLBACK':'false', 'LLM_MAX_CALLS':'10'}
    env.pop('VERCEL', None)
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1', 0))
        port = port_socket.getsockname()[1]
    with log.open('wb') as output:
        process = subprocess.Popen([sys.executable, '-m', 'scripts.serve_private', '--port', str(port)],
                                   cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=3, trust_env=False) as client:
                deadline = time.monotonic()+30
                while True:
                    if process.poll() is not None:
                        raise AssertionError(f'service exited during startup: {log.read_text()}')
                    try:
                        if client.get('/health').status_code == 200:break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() >= deadline:raise AssertionError('service startup timed out')
                    time.sleep(.1)
                yield client
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)


def approval(client, identifier):
    deadline = time.monotonic()+20
    while True:
        response = client.get(f'/runs/{identifier}/approval')
        if response.status_code == 200:
            overview = client.get(f'/runs/{identifier}/overview')
            overview.raise_for_status()
            if overview.json()['run']['status'] == 'awaiting_approval':return response.json()
        if response.status_code not in (200, 404):response.raise_for_status()
        if time.monotonic() >= deadline:raise AssertionError('approval did not become available')
        time.sleep(.1)


def test_process_restart_preserves_pending_review_and_input(source, tmp_path):
    # This permission assertion applies only to generated test fixtures.
    inputs = tmp_path/'release'
    build(source, inputs, {**PROVENANCE, 'permission_status':'private_contest_use_confirmed'})
    manifest = verify(inputs)
    state = tmp_path/'state'
    with server(inputs, state, tmp_path/'first.log') as client:
        ready = client.get('/readiness').json()
        assert ready['ready'] and ready['analysis']['geometry'] == 'administrative_boundaries'
        row = client.get('/analysis/groups?week=all&card_age=all').json()['segments'][0]
        response = client.post('/scenarios/run', json={'id':'restart-fixture', 'type':'monthly',
            'sim_time':'2025-07-01T09:00:00+09:00',
            'payload':{'workflow_version':'regional-workflow-1', 'research_gaps':False,
                       'task':{'sgg':row['sgg'], 'dong_cd':row['dong_cd'], 'sex':row['sex'],
                               'age_group':row['age_group'], 'ym':row['ym'], 'as_of':'2025-07-01'}}}, timeout=10)
        assert response.status_code == 202
        identifier = response.json()['id']
        before = approval(client, identifier)
        assert before['approval']['status'] == 'pending'
    with server(inputs, state, tmp_path/'second.log') as client:
        assert approval(client, identifier) == before
        assert client.get('/readiness').json()['ready']
    assert verify(inputs) == manifest
