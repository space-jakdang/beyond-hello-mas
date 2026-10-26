import csv
import io

import pytest

from backend.tools.card_alarm_v4 import CARD_AGE_BANDS, CardAlarmV4, parse


def card(region="강남", sex="M", age="20대", week="07/07", v=0, n=0, alarm=0, vr="", nr=""):
    return {
        "지역": region, "성": "남" if sex == "M" else "여", "연령대": age, "주": week,
        "V배": vr, "N배": nr, "V단계": str(v), "N단계": str(n), "경보": str(alarm),
        "약기준": "0.95", "강기준": "0.90",
    }


def csv_bytes(rows):
    fields = ["지역", "성", "연령대", "주", "V배", "N배", "V단계", "N단계", "경보", "약기준", "강기준"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def test_v4_card_preserves_none_weak_strong_and_warmup():
    rows = [
        CardAlarmV4(source_region="강남", sex="M", source_age_band="20대", week="2025-07-07",
                    v_ratio=None, n_ratio=None, v_stage=0, n_stage=0, alarm_stage=0,
                    baseline_status="unavailable", weak_threshold=.95, strong_threshold=.90),
        CardAlarmV4(source_region="강남", sex="M", source_age_band="20대", week="2025-07-14",
                    v_ratio=.94, n_ratio=.89, v_stage=1, n_stage=2, alarm_stage=1,
                    baseline_status="observed", weak_threshold=.95, strong_threshold=.90),
        CardAlarmV4(source_region="강남", sex="M", source_age_band="20대", week="2025-07-21",
                    v_ratio=.89, n_ratio=.88, v_stage=2, n_stage=2, alarm_stage=2,
                    baseline_status="observed", weak_threshold=.95, strong_threshold=.90),
    ]
    assert [row.alarm_stage for row in rows] == [0, 1, 2]
    assert rows[0].baseline_status == "unavailable"


def test_v4_card_parser_requires_all_region_sex_age_groups_and_consistent_alarm():
    rows = [
        card(region, sex, age)
        for region in ("강남", "춘천") for sex in ("M", "F") for age in CARD_AGE_BANDS
    ]
    assert len(parse(csv_bytes(rows))) == 24
    with pytest.raises(ValueError, match="incomplete"):
        parse(csv_bytes(rows[:-1]))
    rows[0]["경보"] = "1"
    with pytest.raises(ValueError, match="lower V/N stage"):
        parse(csv_bytes(rows))


def test_v4_card_rejects_non_monday_and_fractional_stage():
    with pytest.raises(ValueError, match="2025 Monday"):
        CardAlarmV4(source_region="강남", sex="M", source_age_band="20대", week="2025-07-08",
                    v_ratio=.94, n_ratio=.92, v_stage=0, n_stage=0, alarm_stage=0,
                    baseline_status="observed", weak_threshold=.95, strong_threshold=.90)
    with pytest.raises(ValueError, match="invalid card stage"):
        from backend.tools.card_alarm_v4 import _stage
        _stage("1.5")
