"""Exercise the actual entrypoint with generated local-format inputs, never private data."""
from contextlib import contextmanager
import os
import shlex
import secrets
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest
import yaml

from backend.app.config import ROOT
from scripts.runtime_package import build, encode, verify
from tests.test_runtime_package import source, PROVENANCE


@contextmanager
def server(inputs, state, log, hosted=False):
    env = {**os.environ, 'DATA_MODE':'local', 'RESOURCE_CATALOG':'v3', 'LLM_MODE':'fake',
           'INPUT_ROOT':str(inputs), 'RUNTIME_STORAGE_ROOT':str(state), 'EVALUATION_ID':'',
           'OPENAI_API_KEY':'', 'GOV24_API_KEY':'', 'GOV24_SERVICE_KEY':'',
           'PYTHONUNBUFFERED':'1', 'PERSON_MCP_MODE':'stub', 'MCP_ALLOW_FALLBACK':'false', 'LLM_MAX_CALLS':'10'}
    env.pop('VERCEL', None)
    env.pop('RENDER', None)
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1', 0))
        port = port_socket.getsockname()[1]
    command = [sys.executable, '-m', 'scripts.serve_private', '--port', str(port)]
    basic = None
    if hosted:
        service = yaml.safe_load((ROOT/'deploy/render.yaml').read_text())['services'][0]
        variables = {row['key']:str(row['value']) for row in service['envVars'] if 'value' in row}
        assert variables['RUNTIME_STORAGE_ROOT'] == service['disk']['mountPath']
        assert service['numInstances'] == 1
        password = secrets.token_urlsafe(24)
        basic = httpx.BasicAuth(variables['PRIVATE_HTTP_USER'], password)
        env.update(variables)
        env.update({'PORT':str(port), 'RUNTIME_INPUT_PACKAGE':encode(inputs),
                    'RUNTIME_STORAGE_ROOT':str(state), 'DATA_MODE':'sample', 'RESOURCE_CATALOG':'fixture',
                    'PRIVATE_HTTP_USER':variables['PRIVATE_HTTP_USER'], 'PRIVATE_HTTP_PASSWORD':password})
        command = shlex.split(service['startCommand'])
    with log.open('wb') as output:
        process = subprocess.Popen(command,
                                   cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=3, trust_env=False, auth=basic) as client:
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


@pytest.mark.parametrize(('hosted', 'package_version'), [(False, 1), (True, 1), (False, 2), (True, 2)])
def test_process_restart_preserves_pending_review_and_input(source, tmp_path, hosted, package_version):
    # This permission assertion applies only to generated test fixtures.
    inputs = tmp_path/'release'
    provenance = {**PROVENANCE, 'permission_status':'private_contest_use_confirmed'}
    if package_version == 1:
        build(source, inputs, provenance)
    else:
        from tests.test_runtime_package import create_source
        from tests.test_runtime_package_v2 import v2_source
        catalog = tmp_path/'catalog-v1'
        build(source, catalog, provenance)
        build(v2_source(tmp_path/'source-v2'), inputs, provenance,
              package_version=2, catalog_from_package=catalog)
    manifest = verify(inputs)
    state = tmp_path/'state'
    with server(inputs, state, tmp_path/'first.log', hosted=hosted) as client:
        if hosted:
            service = yaml.safe_load((ROOT/'deploy/render.yaml').read_text())['services'][0]
            assert service['healthCheckPath'] == '/healthz'
            assert 'maxShutdownDelaySeconds' not in service
            assert client.get('/healthz', auth=None).status_code == 200
            assert client.head('/healthz', auth=None).status_code == 200
            assert client.post('/healthz', auth=None).status_code == 401
            for path in ['/', '/workspace', '/health', '/readiness', '/analysis/groups',
                         '/runs', '/runs/missing/traces/stream', '/runs/missing/overview',
                         '/runs/missing/policy-design/export.pdf', '/healthz/private']:
                response = client.get(path, auth=None)
                assert response.status_code == 401, path
                assert response.headers['www-authenticate'].startswith('Basic ')
                assert response.headers['cache-control'] == 'no-store'
            assert client.get('/runs', auth=('reviewer', 'wrong')).status_code == 401
            assert client.get('/runs', auth=None, headers={'Authorization':'Bearer invalid'}).status_code == 401
            assert client.post('/scenarios/run', auth=None, json={}).status_code == 401
        ready = client.get('/readiness').json()
        assert ready['ready']
        if package_version == 1:
            assert ready['analysis']['geometry'] == 'administrative_boundaries'
            row = client.get('/analysis/groups?week=all&card_age=all').json()['segments'][0]
            workflow = {'workflow_version':'regional-workflow-1', 'research_gaps':False,
                        'task':{'sgg':row['sgg'], 'dong_cd':row['dong_cd'], 'sex':row['sex'],
                                'age_group':row['age_group'], 'ym':row['ym'], 'as_of':'2025-07-01'}}
        else:
            groups = client.get('/analysis/groups?workflow_version=current').json()
            assert groups['metadata']['workflow_version'] == 'regional-workflow-2'
            assert ready['analysis']['workflow_version'] == 'regional-workflow-2'
            assert ready['analysis']['boundary'] == {'matched': 47, 'total': 47}
            row = next(row for row in groups['segments'] if row['assessment_status'] == 'assessed')
            workflow = {'workflow_version':'regional-workflow-2', 'research_gaps':False,
                        'task':{'sgg':row['sgg'], 'dong_cd':row['dong_cd'], 'sex':row['sex'],
                                'source_age_band':row['source_age_band'],
                                'as_of':'2025-07-01', 'card_week':groups['metadata']['selected_week']}}
        response = client.post('/scenarios/run', json={'id':'restart-fixture', 'type':'monthly',
            'sim_time':'2025-07-01T09:00:00+09:00', 'payload':workflow}, timeout=10)
        assert response.status_code == 202, response.text
        identifier = response.json()['id']
        before = approval(client, identifier)
        assert before['approval']['status'] == 'pending'
        traces = client.get(f'/runs/{identifier}/overview').json()['traces']
        proposals = client.get(f'/policy-proposals/{identifier}').json()
        proposal = proposals['sets'][0]
        report_path = f"/policy-proposals/{identifier}/{proposal['dong_cd']}/download/"
        report_params = {'version':proposal['version'], 'revision':proposal['review_revision']}
        assert client.get(report_path+'pdf', params=report_params).content.startswith(b'%PDF')
        with sqlite3.connect(state/'local/events.sqlite3') as db:
            ledger = db.execute('SELECT * FROM llm_calls ORDER BY run_id,call_key').fetchall()
        assert ledger
    with server(inputs, state, tmp_path/'second.log', hosted=hosted) as client:
        assert approval(client, identifier) == before
        assert client.get(f'/runs/{identifier}/overview').json()['traces'] == traces
        assert client.get(f'/policy-proposals/{identifier}').json() == proposals
        pdf = client.get(report_path+'pdf', params=report_params)
        word = client.get(report_path+'docx', params=report_params)
        assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
        assert word.status_code == 200 and word.content.startswith(b'PK')
        with sqlite3.connect(state/'local/events.sqlite3') as db:
            assert db.execute('SELECT * FROM llm_calls ORDER BY run_id,call_key').fetchall() == ledger
        assert client.get('/readiness').json()['ready']
        if package_version == 2:
            assert client.get('/analysis/groups?workflow_version=current').json()['metadata']['workflow_version'] == 'regional-workflow-2'
    assert verify(inputs) == manifest
