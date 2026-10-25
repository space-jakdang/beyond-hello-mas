import json
from uuid import uuid4

from backend.regional_batch import BatchRequest, create
from tests.v4_support import group_data
from tests.test_graph import service


def request(sgg):
    return BatchRequest.model_validate({
        "request_id": str(uuid4()), "workflow_version": "regional-workflow-2",
        "task": {"sgg": sgg, "as_of": "2026-10-25", "card_week": "2025-12-15"},
    })


def test_v4_batch_expands_only_source_age_groups_and_freezes_statuses(service, monkeypatch):
    monkeypatch.setattr("backend.tools.neighborhoods.group_analysis_v4", lambda settings, week: group_data())
    for sgg, expected in (("11230", 12), ("32010", 10)):
        req = request(sgg)
        body = create(service, req)
        assert len(body["children"]) == expected
        assert len({child["source_age_band"] for child in body["children"]}) == (6 if sgg == "11230" else 5)
        assert {child["sex"] for child in body["children"]} == {"M", "F"}
        assert all(child["run_id"] for child in body["children"])
        assert create(service, req) == body
        assessments = {}
        with service.store.connection() as db:
            for row in db.execute("SELECT assessment FROM regional_batch_children WHERE batch_id=?", (body["id"],)):
                assessment = json.loads(row[0])
                if assessment:
                    segment = assessment["segments"][0]
                    assessments[(segment["source_age_band"], segment["sex"])] = segment
        if sgg == "32010":
            assert assessments[("30대", "M")]["assessment_status"] == "small_population_hold"
            assert assessments[("40대", "F")]["assessment_status"] == "insufficient_evidence"


def test_v4_batch_rejects_legacy_age_selection_fields():
    import pytest
    with pytest.raises(ValueError, match="source_age_band and task.card_week"):
        BatchRequest.model_validate({
            "request_id": str(uuid4()), "workflow_version": "regional-workflow-2",
            "task": {"sgg": "11230", "as_of": "2026-10-25", "card_week": "2025-12-15"},
            "age_group": "youth",
        })
