import asyncio
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.agents.llm import Agents, validate_output
from backend.agents.scale import ScaleAdapter, validate_responses, validate_score
from backend.app.config import Settings
from backend.app.contracts import Run
from backend.events import EventStore, utcnow
from backend.tools.catalog import load_catalog

SIM = '2025-07-01T00:00:00Z'


@pytest.fixture
def store(tmp_path):
    store = EventStore(tmp_path / 'events.sqlite3')
    store.create_run(Run(id='r', scenario_id='s', thread_id='r', status='running', data_mode='sample',
        llm_mode='fake', input_version='1', rule_version='1', model_version='fake', prompt_version='1',
        catalog_version='synthetic-1', started_at=utcnow()))
    return store


def test_agent_boundaries_and_cached_calls(store):
    settings = Settings(_env_file=None, llm_mode='fake', llm_max_calls=1)
    agents = Agents(store, settings)
    first = agents.call('r', SIM, 'analysis', {'text': '합성 입력'})
    assert agents.call('r', SIM, 'analysis', {'text': '합성 입력'}) == first
    assert len([t for t in store.traces('r') if t['kind'] == 'llm_call']) == 1
    with pytest.raises(ValueError, match='budget'):
        agents.call('r', SIM, 'route', {'text': '이력'})
    with pytest.raises(ValidationError):
        validate_output('analysis', {**first.model_dump(), 'stage': 5}, {})
    with pytest.raises(ValidationError):
        validate_output('route', {'route': 'bypass_approval', 'reason': ''}, {})
    candidate = load_catalog(Path('data/sample/resources.csv'))[0].model_dump(mode='json')
    with pytest.raises(ValueError, match='IDs'):
        validate_output('recommendations', {'items': [{'resource_id': 'invented', 'explanation': '', 'evidence': []}]}, {'candidates': [candidate]})
    with pytest.raises(ValueError, match='evidence'):
        validate_output('recommendations', {'items': [{'resource_id': candidate['id'], 'explanation': '',
            'evidence': [{'field': 'eligibility', 'value': 'fabricated'}]}]}, {'candidates': [candidate]})
    with pytest.raises(ValueError, match='resource IDs'):
        validate_output('draft', {'text': 'test', 'resource_ids': ['outside']}, {'resource_ids': []})


def test_live_error_redaction_and_reservation(store, monkeypatch):
    import backend.agents.llm as module
    marker = 'PRIVATE_SECRET_MARKER_FOR_ERROR'
    settings = Settings(_env_file=None, llm_mode='live', openai_api_key=marker, openai_model='test-snapshot',
        llm_budget_usd=1, input_usd_per_million=1, output_usd_per_million=1, price_version='test-only')
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['max_retries'] == 0
            self.responses = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def parse(self, **kwargs):
            assert kwargs['store'] is False
            raise RuntimeError(marker)
    monkeypatch.setattr(module, 'OpenAI', Client)
    agents = Agents(store, settings)
    with pytest.raises(ValueError) as error:
        agents.call('r', SIM, 'analysis', {'text': 'synthetic'})
    assert marker not in str(error.value)
    assert marker not in json.dumps(store.traces('r'))
    with store.connection() as db:
        row = db.execute('SELECT status,reserve_usd,body FROM llm_calls').fetchone()
    assert row['status'] == 'error' and row['reserve_usd'] > 0 and marker not in row['body']
    with pytest.raises(ValueError, match='previous call'):
        agents.call('r', SIM, 'analysis', {'text': 'synthetic'})


def test_scale_input_validation_and_pending(store):
    adapter = ScaleAdapter(store, Settings(_env_file=None))
    assert adapter.score('r', SIM, None)['status'] == 'assessment_pending'
    for value in (True, 1.0, '1', 4, -1):
        with pytest.raises(ValueError):
            validate_responses({**{f'q{i}': 0 for i in range(1,7)}, 'q1': value})
    with pytest.raises(ValueError):
        validate_responses({'q1': 0})
    with pytest.raises(ValueError):
        validate_score({'scale_id': 'lsis-6', 'subscales': {}})


@pytest.mark.skipif(not os.environ.get('MCP_PYTHON'), reason='private MCP installation not configured')
def test_actual_mcp_and_same_package_fallback(store, monkeypatch):
    settings = Settings(_env_file=None, mcp_allow_fallback=True)
    adapter = ScaleAdapter(store, settings)
    responses = {'q1': 2, 'q2': 1, 'q3': 2, 'q4': 2, 'q5': 2, 'q6': 2}
    remote = adapter.score('r', SIM, responses)
    assert remote['path'] == 'mcp_stdio'
    assert remote['result']['subscales'] == {'loneliness': 3, 'support': 4, 'network': 4}
    assert {r['label'] for r in remote['result']['matched']} == {'외로움 고위험군', '사회적 고립 고위험군'}
    async def timeout(*args):
        raise TimeoutError('simulated transport timeout')
    monkeypatch.setattr(adapter, 'remote', timeout)
    fallback = adapter.score('r', SIM, responses)
    assert fallback['path'] == 'same_package_python_fallback'
    assert remote['result'] == fallback['result'] and remote['package'] == fallback['package']
    async def invalid(*args):
        raise ValueError('invalid input/protocol response')
    monkeypatch.setattr(adapter, 'remote', invalid)
    with pytest.raises(ValueError):
        adapter.score('r', SIM, responses)


def test_live_success_records_usage_and_budget_blocks_before_call(store, monkeypatch):
    from types import SimpleNamespace
    from backend.agents.schemas import Analysis
    import backend.agents.llm as module
    settings = Settings(_env_file=None, llm_mode='live', openai_api_key='test-placeholder', openai_model='test-snapshot',
        llm_budget_usd=1, input_usd_per_million=1, output_usd_per_million=2, price_version='fixture')
    class Usage:
        input_tokens = 10
        output_tokens = 20
        def model_dump(self, **kwargs): return {'input_tokens': 10, 'output_tokens': 20}
    class Client:
        def __init__(self, **kwargs): self.responses = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def parse(self, **kwargs):
            assert kwargs['model'] == 'test-snapshot' and 'temperature' not in kwargs
            return SimpleNamespace(status='completed', model='test-snapshot', usage=Usage(),
                output_parsed=Analysis(summary='synthetic response', causes=[], needs=[], review_required=True))
    monkeypatch.setattr(module, 'OpenAI', Client)
    agents = Agents(store, settings)
    assert agents.call('r', SIM, 'analysis', {'text': 'synthetic'}).summary == 'synthetic response'
    trace = next(t for t in store.traces('r') if t['kind'] == 'llm_result')
    assert (trace['tokens_in'], trace['tokens_out']) == (10, 20)
    assert trace['payload']['cost_usd'] == pytest.approx(.00005)
    settings.llm_budget_usd = .000001
    with pytest.raises(ValueError, match='budget'):
        agents.call('r', SIM, 'analysis', {'text': 'another'})


def test_real_timeout_path_does_not_hide_failure(store, monkeypatch):
    adapter = ScaleAdapter(store, Settings(_env_file=None, mcp_python='unused', mcp_timeout_seconds=.01))
    monkeypatch.setattr(adapter, 'local_python', lambda *args: {'package_version': 'fixture'})
    async def slow(*args):
        await asyncio.sleep(1)
    monkeypatch.setattr(adapter, 'remote', slow)
    with pytest.raises(ValueError, match='fallback disabled'):
        adapter.score('r', SIM, {f'q{i}': 0 for i in range(1,7)})
