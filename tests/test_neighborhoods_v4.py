from datetime import date

from backend.app.config import Settings
from backend.tools import neighborhoods
from backend.tools.card_alarm_v4 import CARD_AGE_BANDS, CardAlarmV4
from backend.tools.segments_v4 import FRAME_BY_AGE, STAGE_LABEL, SegmentV4


def test_group_analysis_v4_uses_one_week_and_preserves_missing_dong_age(monkeypatch):
    rows = [
        SegmentV4(
            source_region="강남", sgg="11230", dong_cd="11230001", dong_nm="개포3동",
            source_dong_name="일원2동", sex=sex, source_age_band=age, frame=FRAME_BY_AGE[age],
            source_bands={"dong_stage_age": [age]}, source_stage=stage,
            source_stage_label=STAGE_LABEL[stage],
            assessment_status="assessed" if stage > 0 else "small_population_hold",
            base_stage=stage if stage > 0 else None, weakness_count=1, reason="검증",
            population=600,
        )
        for age, sex, stage in (("20대", "M", 3), ("30대", "M", 0), ("30대", "F", 2),
                                ("40대", "M", 0), ("40대", "F", 0))
    ]
    cards = [
        CardAlarmV4(
            source_region=region, sex=sex, source_age_band=age, week=date(2025, 7, 7),
            v_ratio=.99, n_ratio=.99, v_stage=0, n_stage=0, alarm_stage=0,
            baseline_status="observed", weak_threshold=.95, strong_threshold=.90,
        )
        for region in ("강남", "춘천") for sex in ("M", "F") for age in CARD_AGE_BANDS
    ]
    monkeypatch.setattr("backend.tools.segments_v4.load_segments", lambda settings: (rows, {"dataset_version": "v4"}))
    monkeypatch.setattr("backend.tools.card_alarm_v4.load", lambda settings: (cards, {"sha256": "card-hash"}))
    monkeypatch.setattr(neighborhoods, "geometry", lambda settings, dongs: ({"features": []}, {"version": "fixture"}, []))

    result = neighborhoods.group_analysis_v4(Settings(data_mode="local"), "2025-07-07")

    assert result["period_aggregate"] is True
    assert result["metadata"]["selected_week"] == "2025-07-07"
    assert result["metadata"]["source"]["dataset_version"] == "v4"
    assert result["weekly"]["selected_week"] == "2025-07-07"
    assert result["dongs"] == [{
        "dong_cd": "11230001", "dong_nm": "개포3동", "sgg": "11230",
        "stage": 3, "missing_age_bands": 1,
    }]
    assert len(result["segments"]) == 5
    assert result["coverage"] == {"matched": 0, "total": 1, "unmatched_codes": []}
