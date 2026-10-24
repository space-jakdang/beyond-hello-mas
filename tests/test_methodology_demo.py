import pytest
from tests.test_graph import service
from scripts.prepare_methodology_demo import prepare


def test_three_demo_paths_use_real_saved_decisions_without_touching_sources(service):
    from backend.tools.segments_v3 import load_segments
    before=load_segments(service.settings)
    result=prepare(service)
    assert not result['replay'] and len(result['cases'])==3
    assert load_segments(service.settings)==before
    for case in result['cases']:
        proposal=service.approval(case['run_id'])['proposal']
        with service.store.connection() as db:assert db.execute('SELECT COUNT(*) FROM linkages WHERE run_id=?',(case['run_id'],)).fetchone()[0]==0
        assert service.store.get_run(case['run_id']).status=='awaiting_approval'
        if case['case']=='revision':
            stats=proposal['workflow']['statistics']
            assert [entry['phase'] for entry in stats['review_history']]==['initial','final']
            assert proposal['workflow']['analysis']==stats['revised_plan']
        if case['case']=='unconfirmed_need':assert all(row['policy_gap']['status']=='needs_unconfirmed' for row in proposal['assignments'])
    service.settings.data_mode='local'
    with pytest.raises(ValueError,match='sample/fake'):prepare(service)
