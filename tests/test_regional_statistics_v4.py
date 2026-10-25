from types import SimpleNamespace

from backend.agents.workflow import methodology, model_observations, model_summary, observations
from backend.tools.regional_resources import candidates, source_age_ranges
from backend.tools.regional_statistics import run_tool, summary, trend
from backend.tools.regional_task import assess, task_from
from tests.v4_support import group_data


def test_v4_statistics_keep_ordinal_stages_and_weekly_cards_separate(monkeypatch):
    data = group_data()
    monkeypatch.setattr("backend.tools.neighborhoods.group_analysis_v4", lambda settings, week: data)
    assessment = assess(SimpleNamespace(data_mode="local"), task_from({
        "workflow_version": "regional-workflow-2",
        "task": {"sgg": "11230", "sex": "M", "source_age_band": "20대",
                 "as_of": "2026-10-25", "card_week": "2025-12-15"},
    }))

    result = summary(assessment)
    series = trend(None, assessment)
    sensitivity = run_tool("sensitivity", None, assessment)
    checked = run_tool("source_check", None, assessment)

    assert result["observed"] == 1 and result["stage_counts"] == {"2": 1}
    assert result["continuous_index_summary"] is None
    assert result["distributions"][0]["source_age_band"] == "20대"
    assert result["policy_needs"]["profiles"][0]["needs"] == []
    assert result["policy_needs"]["profiles"][0]["priority_midrank"] is None
    assert result["insights"]["status"] == "not_applicable"
    assert series["series"][0]["points"][0]["week"] == "2025-12-15"
    assert "monthly stage series" in series["scope"]
    assert sensitivity["status"] == "not_applicable" and sensitivity["items"][0]["stages"] is None
    assert checked["items"][0]["assessment_status"] == "assessed"
    assert checked["items"][0]["card_source_age_bands"] == ["20대"]

    rows = candidates(assessment, {"status": "reviewed", "summary": result}, [])
    assert rows[0]["reason"] == "unmapped_evidence"
    assert rows[0]["source_age_ranges"] == [(20, 29)]
    assert rows[0]["catalog_filter_performed"] is False
    assert source_age_ranges({"dong_stage_age": ["20대", "70대+"]}) == [(20, 29), (70, 120)]
    assert methodology(assessment)["continuous_metric"] is False
    packed = model_observations([series, checked, sensitivity])
    assert packed[0]["point_columns"][0] == "week"
    assert packed[1]["item_columns"][1] == "source_age_band"
    assert packed[1]["item_columns"][-2:] == ["card_evidence", "card_alarm_status"]
    assert model_summary(result)["data_readiness"]["cohorts"][0]["source_age_band"] == "20대"
    assert observations(assessment)[0]["source_age_band"] == "20대"
    assert observations(assessment)[0]["card_source_age_bands"] == ["20대"]
