from datetime import date

from backend.tools.card_alarm_v4 import CARD_AGE_BANDS, CardAlarmV4
from backend.tools.region_stage_v4 import classify
from backend.tools.segments_v4 import FRAME_BY_AGE, SOURCE_AGE_BANDS, STAGE_LABEL, SegmentV4

WEEK = date(2025, 12, 15)


def group_data():
    segments = []
    codes = {"강남": ("11230", "11230001", "개포3동"), "춘천": ("32010", "32010001", "교동")}
    for region, bands in SOURCE_AGE_BANDS.items():
        sgg, code, dong = codes[region]
        for age in bands:
            for sex in ("M", "F"):
                stage = 0 if (region, age, sex) == ("춘천", "30대", "M") else -1 if (region, age, sex) == ("춘천", "40대", "F") else 2
                segments.append(SegmentV4(
                    source_region=region, sgg=sgg, dong_cd=code, dong_nm=dong,
                    source_dong_name=dong, sex=sex, source_age_band=age,
                    frame=FRAME_BY_AGE[age], source_bands={"dong_stage_age": [age]},
                    source_stage=stage, source_stage_label=STAGE_LABEL[stage],
                    assessment_status="small_population_hold" if stage == 0 else "insufficient_evidence" if stage == -1 else "assessed",
                    base_stage=stage if stage > 0 else None, weakness_count=1, reason="synthetic fixture",
                    population=600,
                ))
    cards = []
    for region in ("강남", "춘천"):
        for sex in ("M", "F"):
            for age in CARD_AGE_BANDS:
                v, n = (2, 2) if (region, sex, age) == ("춘천", "F", "70대+") else (1, 1) if (region, sex, age) == ("강남", "M", "20대") else (0, 0)
                cards.append(CardAlarmV4(
                    source_region=region, sex=sex, source_age_band=age, week=WEEK,
                    v_ratio=.89 if v == 2 else .94 if v == 1 else .99,
                    n_ratio=.89 if n == 2 else .94 if n == 1 else .99,
                    v_stage=v, n_stage=n, alarm_stage=min(v, n), baseline_status="observed",
                    weak_threshold=.95, strong_threshold=.90,
                ))
    result = classify(segments, cards, WEEK)
    return {"segments": result["segments"],
            "weekly": {"signals": [row.model_dump(mode="json") for row in cards]},
            "metadata": {**result["metadata"], "dataset_version": "seohee-region-20261025-1"}}
