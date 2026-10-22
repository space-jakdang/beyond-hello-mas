import pytest
from backend.tools.regional_task import RegionalTask, assess, task_from
from tests.test_graph import service


def task(**changes):
    return RegionalTask.model_validate({'sgg':'11230','ym':'2025-09','as_of':'2026-10-21',
                                      'sex':'M','age_group':'youth',**changes})


def test_assessment_is_scoped_reproducible_and_versioned(service):
    result=assess(service.settings,task())
    assert result==assess(service.settings,task())
    assert result['segments'] and all(r['sgg']=='11230' and r['sex']=='M' and r['ym']=='2025-09' for r in result['segments'])
    assert all(r['evidence_id'] and r['stage_label'] for r in result['segments'])
    assert result['metadata']['card_signals_applied'] is False
    assert result['metadata']['provisional'] is True
    with pytest.raises(ValueError):assess(service.settings,task(dong_cd='11230999'))


def test_invalid_scope_and_time_are_rejected():
    for changes in ({'dong_cd':'32010101'},{'as_of':'2025-08-31'},{'ym':'2025-13'},{'sgg':'99999'}):
        with pytest.raises(ValueError):task(**changes)
    with pytest.raises(ValueError):task_from({'workflow_version':'invented'})


def test_graph_keeps_task_scope_and_rejects_unknown_version(service):
    from tests.test_graph import scenario
    run=service.start(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    assert run.status=='awaiting_approval'
    classification=next(t['payload'] for t in service.store.traces(run.id,limit=1000) if t['agent']=='classify' and t['kind']=='node_end')
    assert classification['task']['sgg']=='11230'
    assert classification['metadata']['card_signals_applied'] is False
    assert all(r['sex']=='M' and r['age_group']=='youth' for r in classification['segments'])
    with pytest.raises(ValueError):service.register(scenario('monthly',workflow_version='invalid'))
