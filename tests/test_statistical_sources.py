from copy import deepcopy
from backend.tools.statistical_sources import readiness
from backend.tools.regional_task import assess
from tests.test_regional_task import task
from tests.test_graph import service


def test_source_inventory_never_uses_population_as_eligibility_denominator(service):
    assessment=assess(service.settings,task())
    result=readiness(assessment)
    assert result['external_source_added'] is False
    assert all(c['comparison_ready'] for c in result['cohorts'])
    assert all(not p['eligible_denominator'] for c in result['cohorts'] for p in c['population_context'])
    assert all(c['synthetic'] for c in result['cohorts'])
    changed=deepcopy(assessment)
    for row in changed['segments']:
        row.update(value=None,residents=None,ym=None)
    empty=readiness(changed)
    assert all(c['observed']==0 and c['monthly_points']==0 and not c['comparison_ready'] and not c['population_context'] for c in empty['cohorts'])


def test_distinct_periods_and_source_ages_never_join(service):
    assessment=assess(service.settings,task())
    original=len(readiness(assessment)['cohorts'])
    assessment['segments'][0]['source_period']='different-period'
    assessment['segments'][1]['source_bands']={'different_source':['80+']}
    assert len(readiness(assessment)['cohorts'])==original+2


def test_model_summary_omits_repeated_population_rows_but_preserves_saved_inventory(service):
    from backend.agents.workflow import model_summary
    from backend.tools.regional_statistics import summary
    assessment=assess(service.settings,task())
    saved=summary(assessment);compact=model_summary(saved)
    assert all('population_context' not in c for c in compact['data_readiness']['cohorts'])
    assert any(c['population_context'] for c in saved['data_readiness']['cohorts'])
    assert saved['policy_needs']['population_estimate'] is None
    assessment['data_mode']='local'
    assert readiness(assessment)['cohorts'][0]['population_context'][0]['kind']=='telecom_monthly_average'
    for r in assessment['segments']:r['sgg']='32010'
    assert readiness(assessment)['cohorts'][0]['population_context'][0]['kind']=='registered_population_context'
