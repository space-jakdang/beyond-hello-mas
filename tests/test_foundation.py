import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.contracts import Alert, Approval, Scenario, Segment, Trace
from backend.app.main import create_app
from scripts.check_public import violations
from scripts.sample import sample


def test_health_and_mode_separation(tmp_path, monkeypatch):
    import backend.app.config as config
    monkeypatch.setattr(config, "ROOT", tmp_path)
    settings = Settings(_env_file=None, data_mode="local", llm_mode="fake")
    assert settings.data_dir.name == settings.runtime_dir.name == "local"
    assert TestClient(create_app(settings)).get('/health').json() == {
        'status': 'ok', 'data_mode': 'local', 'llm_mode': 'fake', 'capabilities': ['foundation']}


@pytest.mark.parametrize('values', [dict(data_mode='oops'), dict(llm_mode='oops'),
                                  dict(llm_mode='live', openai_api_key='')])
def test_invalid_settings(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_scenario_time_and_answer_separation():
    assert sample().sim_time.isoformat() == '2025-07-01T09:00:00+09:00'
    for payload in ({'expected': {}}, {'nested': [{'expected': 'answer'}]}):
        with pytest.raises(ValidationError):
            Scenario(**{**sample().model_dump(), 'payload': payload})
    with pytest.raises(ValidationError):
        Scenario(**sample().model_dump(), expected={})


@pytest.fixture
def segment():
    return dict(ym='2025-07', sgg='11230', dong_cd='11230511', dong_nm='합성동',
                age_band='20s', x=1, y=2, crs='synthetic-cartesian', coordinate_source='synthetic',
                indicators={'ind_activity': None}, indicator_version='draft-1', residents=0, blind_flag=False)


def test_segment(segment):
    assert Segment(**segment).indicators['ind_activity'] is None
    for change in ({'ym': '2025-13'}, {'dong_cd': '123'}, {'sgg': '11111'},
                   {'age_band': 'other'}, {'residents': -1}, {'x': float('nan')}):
        with pytest.raises(ValidationError):
            Segment(**{**segment, **change})


def test_trace():
    trace = dict(run_id='r', scenario_id='s', seq=1, wall_ts='2025-07-01T09:00:00+09:00',
                 sim_ts='2025-07-01T09:00:00', agent='system', kind='node_start', payload={})
    assert Trace(**trace).wall_ts.isoformat() == '2025-07-01T00:00:00+00:00'
    for change in ({'kind': 'unknown'}, {'seq': 0}, {'wall_ts': '2025-07-01T09:00:00'}, {'latency_ms': -1}):
        with pytest.raises(ValidationError):
            Trace(**{**trace, **change})


def test_approval_and_alert():
    with pytest.raises(ValidationError):
        Approval(id='a', run_id='r', snapshot_version='1', status='approved')
    with pytest.raises(ValidationError):
        Alert(id='a', run_id='r', type='approval_requested', status='created', created_at='2025-07-01T00:00:00Z')


@pytest.mark.parametrize('path', ['.local-plans/test.md', 'data/local/a.csv', 'runtime/sample/a.json',
                                  'eval/local/a.json', '.env', '.env.prod', 'x.db-wal', 'x.sqlite3-shm'])
def test_private_paths(path):
    assert violations(path, b'harmless')


def test_secrets_and_examples():
    assert not violations('.env.example', b'OPENAI_API_KEY=\nDATA_MODE=sample\n')
    assert violations('example.txt', b'sk-' + b'x' * 30)
    assert violations('.env.example', b'OPENAI_API_KEY=' + b'x' * 10)
    assert not violations('data/sample/scenario.json', b'{"synthetic": true}')


def test_eval_is_incomplete():
    result = subprocess.run(['uv', 'run', 'python', '-m', 'scripts.evaluate'], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)['evaluated_scenarios'] == 0


def test_generated_contracts_current():
    from backend.app import contracts
    schemas = json.loads(Path('frontend/src/contracts.schema.json').read_text())
    assert schemas
    for name, schema in schemas.items():
        assert schema == getattr(contracts, name).model_json_schema()


def test_guard_reads_index_and_committed_blobs(tmp_path):
    import sys
    checker = Path('scripts/check_public.py').resolve()
    def git(*args):
        return subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init')
    (tmp_path / '.env').write_text('private')
    git('add', '.env')
    (tmp_path / '.env').unlink()
    result = subprocess.run([sys.executable, str(checker)], cwd=tmp_path, capture_output=True)
    assert result.returncode == 1 and b'private path' in result.stdout
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
    result = subprocess.run([sys.executable, str(checker), '--tracked'], cwd=tmp_path, capture_output=True)
    assert result.returncode == 1 and b'private path' in result.stdout


def test_hook_preserves_existing_hook(tmp_path):
    import sys
    installer = Path('scripts/install_hook.py').resolve()
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    subprocess.run([sys.executable, str(installer)], cwd=tmp_path, check=True, capture_output=True)
    hook = tmp_path / '.git/hooks/pre-commit'
    original = hook.read_bytes()
    result = subprocess.run([sys.executable, str(installer)], cwd=tmp_path, capture_output=True)
    assert result.returncode != 0 and hook.read_bytes() == original


def test_alert_rejects_timestamps_ahead_of_state():
    for status, times in [('created', {'received_at': '2025-07-01T00:01:00Z'}),
                          ('received', {'received_at': '2025-07-01T00:01:00Z',
                                        'acknowledged_at': '2025-07-01T00:02:00Z'})]:
        with pytest.raises(ValidationError):
            Alert(id='a', run_id='r', type='crisis', status=status,
                  created_at='2025-07-01T00:00:00Z', **times)


def test_dev_propagates_failure_and_cleans_up(monkeypatch):
    import runpy
    from unittest.mock import Mock
    failed = Mock(returncode=3)
    failed.poll.return_value = 3
    running = Mock(returncode=None)
    running.poll.return_value = None
    monkeypatch.setattr(subprocess, 'Popen', Mock(side_effect=[failed, running]))
    with pytest.raises(SystemExit) as error:
        runpy.run_module('scripts.dev', run_name='__main__')
    assert error.value.code == 3
    running.terminate.assert_called_once()
