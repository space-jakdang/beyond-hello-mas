from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil

import pytest

from backend.app.config import Settings
from backend.app.contracts import Scenario
from backend.events import EventStore
from backend.graph import GraphService, crisis_evidence

SIM = '2025-07-01T09:00:00+09:00'


@pytest.fixture
def service(tmp_path, monkeypatch):
    import backend.app.config as config
    source = config.ROOT / 'data/sample'
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    shutil.copytree(source, tmp_path / 'data/sample')
    settings = Settings(_env_file=None, data_mode='sample', llm_mode='fake')
    return GraphService(EventStore(settings.runtime_dir / 'events.sqlite3'), settings)


def scenario(kind='case', **payload):
    return Scenario(id='test', type=kind, sim_time=SIM, payload=payload or {'text': '상담을 요청합니다'})


def counts(service, run_id):
    with service.store.connection() as db:
        return (db.execute('SELECT COUNT(*) FROM linkages WHERE run_id=?', (run_id,)).fetchone()[0],
                db.execute('SELECT COUNT(*) FROM alerts WHERE run_id=?', (run_id,)).fetchone()[0])


def decide(service, run_id, status='approved', reason=None):
    snapshot = service.approval(run_id)['approval']['snapshot_version']
    return service.decide(run_id, snapshot, status, 'tester', reason)


def test_normal_wait_approve_and_reject(service):
    run = service.start(scenario())
    assert run.status == 'awaiting_approval' and counts(service, run.id) == (0, 1)
    assert service.approval(run.id)['proposal']['assessment'] == 'assessment_pending'
    assert decide(service, run.id).status == 'completed'
    assert counts(service, run.id) == (1, 2)
    assert [t['agent'] for t in service.store.traces(run.id) if t['kind'] == 'node_end'] == [
        'supervisor', 'classify', 'match', 'approval', 'link']
    rejected = service.start(scenario())
    with pytest.raises(ValueError):
        decide(service, rejected.id, 'rejected')
    assert decide(service, rejected.id, 'rejected', '근거 부족').status == 'rejected'
    assert counts(service, rejected.id) == (0, 1)


def test_crisis_bypasses_classifier_and_type_is_not_label(service, monkeypatch):
    def fail(*args):
        raise RuntimeError('LLM/classifier unavailable')
    monkeypatch.setattr(service, 'classify_node', fail)
    run = service.start(scenario('question', nested={'text': '지금 죽고 싶어요'}))
    assert run.status == 'completed' and counts(service, run.id) == (1, 1)
    assert [t['agent'] for t in service.store.traces(run.id) if t['kind'] == 'node_end'] == ['supervisor', 'link']
    assert crisis_evidence({'text': '죽고 싶지 않아요. 자살 예방 교육 안내'}) == []
    with pytest.raises(RuntimeError):
        service.start(scenario('crisis', text='예방 교육 문의'))


def test_concurrent_duplicate_and_conflicting_decisions(service):
    run = service.start(scenario())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: decide(service, run.id), range(8)))
    assert all(r.status == 'completed' for r in results)
    assert counts(service, run.id) == (1, 2)
    run = service.start(scenario())
    def attempt(status):
        try:
            return decide(service, run.id, status, 'test').status
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ['approved', 'rejected']))
    assert outcomes.count('conflict') == 1
    assert counts(service, run.id)[0] == (1 if 'completed' in outcomes else 0)


def test_restart_pending_and_snapshot_binding(service):
    run = service.start(scenario())
    with pytest.raises(ValueError, match='snapshot'):
        service.decide(run.id, 'wrong', 'approved', 'tester')
    restarted = GraphService(EventStore(service.store.path), service.settings)
    restarted.recover()
    assert counts(restarted, run.id) == (0, 1)
    assert decide(restarted, run.id).status == 'completed'
    assert counts(restarted, run.id) == (1, 2)


def test_checkpoint_before_publication_and_after_effect_recovery(service, monkeypatch):
    original_publish = service.publish_approval
    def fail_publish(state):
        raise RuntimeError('crash before approval publication')
    monkeypatch.setattr(service, 'publish_approval', fail_publish)
    with pytest.raises(RuntimeError):
        service.start(scenario())
    run_id = service.store.list_runs()[0]['id']
    with pytest.raises(KeyError):
        service.approval(run_id)
    monkeypatch.setattr(service, 'publish_approval', original_publish)
    service.recover()
    assert service.store.get_run(run_id).status == 'awaiting_approval'
    original_link = service.link_node
    def fail_after_effect(state):
        original_link(state)
        raise RuntimeError('crash after committed side effect')
    monkeypatch.setattr(service, 'link_node', fail_after_effect)
    with pytest.raises(RuntimeError):
        decide(service, run_id)
    assert counts(service, run_id) == (1, 2)
    restarted = GraphService(EventStore(service.store.path), service.settings)
    restarted.recover()
    assert restarted.store.get_run(run_id).status == 'completed'
    assert counts(restarted, run_id) == (1, 2)


def test_decision_durable_before_resume_and_missing_checkpoint(service, monkeypatch):
    run = service.start(scenario())
    original = service.drive
    monkeypatch.setattr(service, 'drive', lambda *args: (_ for _ in ()).throw(RuntimeError('crash before resume')))
    with pytest.raises(RuntimeError):
        decide(service, run.id)
    assert service.approval(run.id)['approval']['status'] == 'approved'
    monkeypatch.setattr(service, 'drive', original)
    service.recover()
    assert counts(service, run.id) == (1, 2)
    pending = service.start(scenario())
    checkpoint = service.settings.runtime_dir / 'checkpoints.sqlite3'
    # Copy the store into a fresh runtime without any checkpoint: approval cannot succeed.
    other = checkpoint.with_suffix('.backup')
    checkpoint.rename(other)
    with pytest.raises(ValueError, match='checkpoint'):
        decide(service, pending.id)
    assert counts(service, pending.id) == (0, 1)


def test_monthly_snapshot_covers_whole_allocation(service):
    run = service.start(scenario('monthly', ym='2025-07'))
    proposal = service.approval(run.id)['proposal']
    assert proposal['scope'] == 'monthly_group_allocation'
    assert len(proposal['assignments']) == 282
    assert counts(service, run.id) == (0, 1)
    assert decide(service, run.id).status == 'completed'
    with service.store.connection() as db:
        linkage = json.loads(db.execute('SELECT body FROM linkages WHERE run_id=?', (run.id,)).fetchone()[0])
    assert linkage['kind'] == 'monthly_group_allocation' and not linkage['external_delivery']


def test_start_recovers_before_first_checkpoint(service, monkeypatch):
    original = service.drive
    monkeypatch.setattr(service, 'drive', lambda *args: (_ for _ in ()).throw(RuntimeError('before graph')))
    with pytest.raises(RuntimeError):
        service.start(scenario())
    run_id = service.store.list_runs()[0]['id']
    monkeypatch.setattr(service, 'drive', original)
    service.recover()
    assert service.store.get_run(run_id).status == 'awaiting_approval'


def test_live_never_silently_uses_fake_and_crisis_still_works(service):
    service.settings.llm_mode = 'live'
    with pytest.raises(ValueError, match='live agent'):
        service.start(scenario())
    assert service.start(scenario(text='죽고 싶어요')).status == 'completed'
