from tests.test_graph import service,scenario


def test_default_monthly_uses_all_eight_groups_and_approval(service):
    run=service.start(scenario('monthly',ym='2025-09'))
    assert run.status=='awaiting_approval' and run.rule_version=='seohee-region-2'
    rows=service.approval(run.id)['proposal']['assignments']
    assert len(rows)==47*8
    assert len({(r['dong_cd'],r['sex'],r['age_group']) for r in rows})==47*8
    assert all(r['ym']=='2025-09' for r in rows)

    classification=next(t['payload'] for t in service.store.traces(run.id) if t['kind']=='node_end' and t['agent']=='classify')
    assert classification['metadata']['selected_week'].startswith('2025-09')
