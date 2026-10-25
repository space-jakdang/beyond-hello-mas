from datetime import date

import pytest

from backend.tools.card_alarm_v4 import CARD_AGE_BANDS, CardAlarmV4
from backend.tools.region_stage_v4 import classify
from backend.tools.segments_v4 import FRAME_BY_AGE, STAGE_LABEL, SegmentV4

WEEK = date(2025, 7, 7)


def segment(region="강남", age="20대", sex="M", stage=3, code="11230001"):
    status = "insufficient_evidence" if stage == -1 else "small_population_hold" if stage == 0 else "assessed"
    return SegmentV4(
        source_region=region, sgg=code[:5], dong_cd=code,
        dong_nm="개포3동" if region == "강남" else "교동", source_dong_name="원천 동명",
        sex=sex, source_age_band=age, frame=FRAME_BY_AGE[age],
        source_bands={"dong_stage_age": [age]}, source_stage=stage,
        source_stage_label=STAGE_LABEL[stage], assessment_status=status,
        base_stage=stage if stage > 0 else None, weakness_count=2, reason="검증 이유",
        population=600,
    )


def card(region, sex, age, v=0, n=0, week=WEEK):
    alarm = min(v, n)
    return CardAlarmV4(
        source_region=region, sex=sex, source_age_band=age, week=week,
        v_ratio=.89 if v == 2 else .94 if v == 1 else .99,
        n_ratio=.89 if n == 2 else .94 if n == 1 else .99,
        v_stage=v, n_stage=n, alarm_stage=alarm, baseline_status="observed",
        weak_threshold=.95, strong_threshold=.90,
    )


def card_set(overrides=None):
    overrides = overrides or {}
    return [
        card(region, sex, age, *overrides.get((region, sex, age), (0, 0)))
        for region in ("강남", "춘천") for sex in ("M", "F") for age in CARD_AGE_BANDS
    ]


def classified(row, overrides=None):
    return classify([row], card_set(overrides))['segments'][0]


def test_card_alarm_uses_min_and_weak_signal_does_not_raise_stage():
    mixed = classified(segment(), {("강남", "M", "20대"): (2, 0)})
    weak = classified(segment(), {("강남", "M", "20대"): (1, 1)})
    assert (mixed["card_alarm_stage"], mixed["final_stage"]) == (0, 3)
    assert mixed["card_alarm_status"] == "none"
    assert (weak["card_alarm_stage"], weak["card_alarm_status"], weak["final_stage"]) == (1, "weak", 3)
    assert weak["card_evidence"][0]["v_ratio"] == .94


def test_strong_alarm_raises_only_assessed_stage_and_caps_at_five():
    overrides = {("강남", "M", "20대"): (2, 2)}
    assert classified(segment(stage=3), overrides)["final_stage"] == 4
    assert classified(segment(stage=5), overrides)["final_stage"] == 5
    for stage in (0, -1):
        result = classified(segment(stage=stage), overrides)
        assert result["final_stage"] is None
        assert result["stage_adjustment"] == 0
        assert result["assessment_status"] == ("small_population_hold" if stage == 0 else "insufficient_evidence")


def test_chuncheon_60_plus_uses_higher_of_60s_and_70_plus():
    result = classified(segment("춘천", "60대+", "F", code="32010001"), {
        ("춘천", "F", "60대"): (1, 1),
        ("춘천", "F", "70대+"): (2, 2),
    })
    assert result["card_source_age_bands"] == ["60대", "70대+"]
    assert result["card_alarm_stage"] == 2
    assert result["final_stage"] == 4
    assert len(result["card_evidence"]) == 2


def test_priority_groups_use_region_specific_oldest_band_and_sort_statuses():
    rows = [
        segment("강남", "60대", "F", code="11230001"),
        segment("강남", "70대+", "F", code="11230001"),
        segment("춘천", "60대+", "F", code="32010001"),
        segment("강남", "20대", "M", code="11230001"),
        segment("강남", "70대+", "M", stage=0, code="11230002"),
        segment("강남", "70대+", "M", stage=-1, code="11230003"),
    ]
    result = classify(rows, card_set())['segments']
    groups = {(r["source_region"], r["source_age_band"], r["sex"], r["source_stage"]): r["priority_group"] for r in result}
    assert groups[("강남", "60대", "F", 3)] is None
    assert groups[("강남", "70대+", "F", 3)] == "older_adult"
    assert groups[("춘천", "60대+", "F", 3)] == "older_adult"
    assert groups[("강남", "20대", "M", 3)] == "male_20s"
    assert result[-2]["source_stage"] == 0 and result[-1]["source_stage"] == -1


def test_classifier_rejects_missing_card_groups_and_unknown_week():
    cards = card_set()
    with pytest.raises(ValueError, match="incomplete"):
        classify([segment()], cards[:-1])
    with pytest.raises(ValueError, match="unknown v4 card week"):
        classify([segment()], cards, "2025-07-14")
