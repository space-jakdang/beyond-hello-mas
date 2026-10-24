from pathlib import Path

import pytest
from backend.app.config import Settings
from scripts.serve_private import prepare
from tests.test_runtime_package import confirmed_package, source


def settings(tmp_path, **changes):
    return Settings(_env_file=None, data_mode='local', llm_mode='fake', resource_catalog='v3',
                    input_root=tmp_path/'inputs', runtime_storage_root=tmp_path/'state', **changes)


def test_private_start_checks_modes_and_roots_before_serving(tmp_path, monkeypatch):
    value = settings(tmp_path)
    monkeypatch.setenv('VERCEL', '1')
    with pytest.raises(ValueError, match='persistent host'):
        with prepare(value):pass
    monkeypatch.delenv('VERCEL')
    for field, replacement in [('data_mode', 'sample'), ('resource_catalog', 'fixture'),
                               ('input_root', None), ('runtime_storage_root', None),
                               ('runtime_storage_root', tmp_path/'inputs/state')]:
        with pytest.raises(ValueError):
            with prepare(value.model_copy(update={field: replacement})):pass


def test_pending_permissions_cannot_serve(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.runtime_package.verify', lambda _: {'provenance': {'permission_status': 'pending'}})
    with pytest.raises(ValueError, match='confirmation'):
        with prepare(settings(tmp_path)):pass
    assert not (tmp_path/'state').exists()


def test_exclusive_runtime_lock_and_release(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.runtime_package.verify', lambda _: {'provenance': {'permission_status': 'private_contest_use_confirmed'}})
    value = settings(tmp_path)
    with prepare(value):
        with pytest.raises(ValueError, match='another private service'):
            with prepare(value):pass
    with prepare(value):pass
    assert (tmp_path/'state/service.lock').is_file()


def test_sample_graph_store_survives_new_service_object(tmp_path):
    from backend.events import EventStore
    from backend.graph import GraphService
    from backend.app.contracts import Scenario
    cfg = Settings(_env_file=None, data_mode='sample', llm_mode='fake',
                   runtime_storage_root=tmp_path/'persistent')
    first = GraphService(EventStore(cfg.runtime_dir/'events.sqlite3'), cfg)
    run = first.start(Scenario(id='persistence-test', type='case', sim_time='2025-07-01T09:00:00+09:00',
                               payload={'text': 'synthetic review request'}))
    assert run.status == 'awaiting_approval'
    before = first.approval(run.id)
    before_traces = first.store.traces(run.id)
    second = GraphService(EventStore(cfg.runtime_dir/'events.sqlite3'), cfg)
    second.recover()
    assert second.approval(run.id) == before
    assert second.store.traces(run.id) == before_traces


def test_second_process_cannot_own_runtime(tmp_path, monkeypatch):
    import subprocess
    import sys
    monkeypatch.setattr('scripts.runtime_package.verify', lambda _: {'provenance': {'permission_status': 'private_contest_use_confirmed'}})
    child = '''
import sys
from pathlib import Path
from backend.app.config import Settings
from scripts.serve_private import prepare
import scripts.runtime_package
scripts.runtime_package.verify = lambda _: {'provenance': {'permission_status':'private_contest_use_confirmed'}}
s = Settings(_env_file=None, data_mode='local', llm_mode='fake', resource_catalog='v3', input_root=Path(sys.argv[1])/'inputs', runtime_storage_root=Path(sys.argv[1])/'state')
try:
    with prepare(s): pass
except ValueError as error:
    if 'another private service' in str(error): sys.exit(0)
    raise
sys.exit(1)
'''
    with prepare(settings(tmp_path)):
        result = subprocess.run([sys.executable, '-c', child, str(tmp_path)], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode()


def test_entrypoint_binds_only_loopback_one_worker(tmp_path, monkeypatch):
    import sys
    import uvicorn
    import backend.app.main
    import scripts.serve_private as entry
    cfg = settings(tmp_path)
    monkeypatch.setattr(entry, 'Settings', lambda: cfg)
    monkeypatch.setattr('scripts.runtime_package.verify', lambda _: {'provenance': {'permission_status': 'private_contest_use_confirmed'}})
    app = object()
    monkeypatch.setattr(backend.app.main, 'create_app', lambda: app)
    calls = []
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(sys, 'argv', ['serve_private', '--port', '8123'])
    entry.main()
    assert calls == [((app,), {'host':'127.0.0.1', 'port':8123, 'workers':1})]


def test_hosted_entrypoint_requires_authentication_and_a_mounted_disk(tmp_path, monkeypatch):
    import scripts.serve_hosted as entry
    monkeypatch.setenv('PRIVATE_HTTP_USER', 'reviewer')
    monkeypatch.setenv('PRIVATE_HTTP_PASSWORD', 'too-short')
    with pytest.raises(ValueError, match='PRIVATE_HTTP_PASSWORD'):entry.main()
    monkeypatch.setenv('PRIVATE_HTTP_PASSWORD', 'synthetic-fixture-password-1234')
    for username in [' ', 'bad:user']:
        monkeypatch.setenv('PRIVATE_HTTP_USER', username)
        with pytest.raises(ValueError, match='PRIVATE_HTTP_USER'):entry.main()
    monkeypatch.setenv('PRIVATE_HTTP_USER', 'reviewer')
    monkeypatch.delenv('RUNTIME_STORAGE_ROOT', raising=False)
    with pytest.raises(ValueError, match='absolute RUNTIME_STORAGE_ROOT'):entry.main()
    monkeypatch.setenv('RUNTIME_STORAGE_ROOT', str(tmp_path))
    monkeypatch.setenv('RENDER', 'true')
    with pytest.raises(ValueError, match='mounted persistent disk'):entry.main()
    monkeypatch.delenv('RENDER')
    monkeypatch.setenv('PORT', '65536')
    with pytest.raises(ValueError, match='PORT'):entry.main()
    monkeypatch.setenv('PORT', '10000')
    monkeypatch.delenv('RUNTIME_INPUT_PACKAGE', raising=False)
    with pytest.raises(ValueError, match='RUNTIME_INPUT_PACKAGE'):entry.main()


def test_hosted_service_cannot_switch_to_an_empty_evaluation_ledger(confirmed_package, tmp_path, monkeypatch):
    from uuid import uuid4
    from scripts.runtime_package import encode
    from scripts.serve_hosted import main
    monkeypatch.delenv('RENDER', raising=False)
    for name,value in {'PRIVATE_HTTP_USER':'reviewer', 'PRIVATE_HTTP_PASSWORD':'synthetic-fixture-password-1234',
                       'RUNTIME_STORAGE_ROOT':str(tmp_path/'state'), 'PORT':'10000', 'LLM_MODE':'fake',
                       'RUNTIME_INPUT_PACKAGE':encode(confirmed_package), 'EVALUATION_ID':str(uuid4())}.items():
        monkeypatch.setenv(name,value)
    with pytest.raises(ValueError, match='clear EVALUATION_ID'):main()
    assert not (tmp_path/'state').exists()
