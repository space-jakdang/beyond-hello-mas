from types import SimpleNamespace

import pytest

from backend.tools.regional_task import assess, task_from
from backend.tools.regional_task_v4 import RegionalTaskV4
from backend.app.contracts import Scenario
from tests.v4_support import group_data


def payload(**updates):
    task = {"sgg": "11230", "sex": "M", "source_age_band": "20대",
            "as_of": "2026-10-25", "card_week": "2025-12-15"}
    return {"workflow_version": "regional-workflow-2", "task": {**task, **updates}}


def test_v4_task_requires_region_age_and_pins_week():
    task = task_from(payload())
    assert isinstance(task, RegionalTaskV4)
    assert task.methodology_version == "regional-workflow-2"
    assert task.card_week.isoformat() == "2025-12-15"
    for updates in ({"source_age_band": "60대+"}, {"card_week": "2025-12-16"},
                    {"card_week": "2026-12-14"}, {"dong_cd": "32010001"}):
        with pytest.raises(ValueError):
            task_from(payload(**updates))
    with pytest.raises(ValueError):
        task_from({"workflow_version": "regional-workflow-1", "task": {}})


def test_v4_assessment_preserves_stage_week_age_and_unassessed_status(monkeypatch):
    data = group_data()
    monkeypatch.setattr("backend.tools.neighborhoods.group_analysis_v4", lambda settings, week: data)
    settings = SimpleNamespace(data_mode="local")
    assessed = assess(settings, task_from(payload()))
    held = assess(settings, task_from(payload(sgg="32010", sex="M", source_age_band="30대")))
    missing = assess(settings, task_from(payload(sgg="32010", sex="F", source_age_band="40대")))
    older = assess(settings, task_from(payload(sgg="32010", sex="F", source_age_band="60대+")))

    assert assessed["period_aggregate"] is True
    assert assessed["metadata"]["workflow_version"] == "regional-workflow-2"
    assert assessed["metadata"]["dataset_version"] == "seohee-region-20261025-1"
    assert assessed["task"]["source_age_band"] == assessed["task"]["age_group"] == "20대"
    assert assessed["task"]["card_week"] == "2025-12-15" and assessed["task"]["ym"] == "2025-12"
    assert len(assessed["segments"]) == 1
    assert assessed["segments"][0]["ym"] is None and assessed["segments"][0]["value"] is None
    assert assessed["segments"][0]["stage"] == 2
    assert assessed["weekly_observations"]
    assert (held["segments"][0]["stage"], held["segments"][0]["assessment_status"]) == (None, "small_population_hold")
    assert (missing["segments"][0]["stage"], missing["segments"][0]["assessment_status"]) == (None, "insufficient_evidence")
    assert older["segments"][0]["card_source_age_bands"] == ["60대", "70대+"]
    assert older["segments"][0]["card_alarm_status"] == "strong"
    assert older["segments"][0]["stage"] == 3
    older["weekly_observations"][0]["baseline_status"] = "unavailable"
    from backend.tools.regional_statistics import trend
    assert trend(None, older)["series"][0]["points"][0]["baseline_status"] == "partial"


def test_v4_assessment_does_not_replace_an_explicit_empty_snapshot(monkeypatch):
    monkeypatch.setattr("backend.tools.neighborhoods.group_analysis_v4",
                        lambda *args: pytest.fail("explicit snapshot must not fall back to local data"))
    with pytest.raises(ValueError, match="no observations"):
        assess(SimpleNamespace(data_mode="local"), task_from(payload()),
               source_data={"segments": [], "weekly": {"signals": []}})


def test_graph_runs_v4_workflow_and_freezes_source_age(tmp_path, monkeypatch):
    import shutil
    import backend.app.config as config
    from backend.app.config import Settings
    from backend.events import EventStore
    from backend.graph import GraphService

    sample = config.ROOT / "data/sample"
    monkeypatch.setattr(config, "ROOT", tmp_path)
    shutil.copytree(sample, tmp_path / "data/sample")
    settings = Settings(_env_file=None, data_mode="sample", llm_mode="fake")
    service = GraphService(EventStore(settings.runtime_dir / "events.sqlite3"), settings)
    data = group_data()
    monkeypatch.setattr("backend.tools.neighborhoods.group_analysis_v4", lambda settings, week: data)
    scenario = Scenario(id="regional-v4", type="monthly", sim_time="2026-10-25T09:00:00+09:00",
        payload={"workflow_version":"regional-workflow-2", "task":{
            "sgg":"11230", "sex":"M", "source_age_band":"20대",
            "as_of":"2026-10-25", "card_week":"2025-12-15"}})

    run = service.start(scenario)
    proposal = service.approval(run.id)["proposal"]

    assert run.status == "awaiting_approval"
    assert run.rule_version == "seohee-region-20261025-1"
    assert proposal["workflow_version"] == "regional-workflow-2"
    assert proposal["assessment"]["metadata"]["analysis_version"] == "v4"
    assert proposal["assessment"]["metadata"]["statistics_version"] == "3"
    assert proposal["assessment"]["task"]["source_age_band"] == "20대"
    assert proposal["assessment"]["metadata"]["selected_week"] == "2025-12-15"
