"""Apply version 4 weekly group alarms to source stages and rank review order."""
from datetime import date

from backend.tools.card_alarm_v4 import CardAlarmV4, validate as validate_cards
from backend.tools.indicators import digest
from backend.tools.segments_v4 import SegmentV4, validate as validate_segments

METHOD_VERSION = "seohee-region-20261025-1"
WORKFLOW_VERSION = "regional-workflow-2"
STAGE_LABEL = {-1: "판정 근거 부족", 0: "판정 보류", 1: "안정", 2: "관심", 3: "주의", 4: "경계", 5: "심각"}


def _card_sources(segment, signals, week):
    bands = ("60대", "70대+") if segment.source_region == "춘천" and segment.source_age_band == "60대+" else (segment.source_age_band,)
    rows = [signals.get((segment.source_region, segment.sex, band, week)) for band in bands]
    if any(row is None for row in rows):
        raise ValueError("weekly card group missing for source age")
    observed = [row for row in rows if row.baseline_status == "observed"]
    return rows, max((row.alarm_stage for row in observed), default=None), bands


def classify(rows: list[SegmentV4], cards: list[CardAlarmV4], week: str | date | None = None):
    validate_segments(rows)
    validate_cards(cards, complete=True)
    weeks = {row.week for row in cards}
    selected_week = max(weeks) if week is None else date.fromisoformat(week) if isinstance(week, str) else week
    if selected_week not in weeks:
        raise ValueError("unknown v4 card week")
    signals = {(row.source_region, row.sex, row.source_age_band, row.week): row for row in cards}
    result = []
    for source in rows:
        evidence, alarm, card_bands = _card_sources(source, signals, selected_week)
        strong = alarm == 2
        final_stage = min(5, source.base_stage + int(strong)) if source.base_stage is not None else None
        priority_group = (
            "male_20s" if source.source_age_band == "20대" and source.sex == "M" else
            "older_adult" if (source.source_region, source.source_age_band) in (("강남", "70대+"), ("춘천", "60대+")) else None
        )
        alarm_status = "baseline_unavailable" if alarm is None else ("none", "weak", "strong")[alarm]
        result.append({
            "dataset_version": source.dataset_version,
            "source_region": source.source_region,
            "sgg": source.sgg,
            "dong_cd": source.dong_cd,
            "dong_nm": source.dong_nm,
            "source_dong_name": source.source_dong_name,
            "sex": source.sex,
            "source_age_band": source.source_age_band,
            "frame": source.frame,
            "source_bands": source.source_bands,
            "source_stage": source.source_stage,
            "source_stage_label": source.source_stage_label,
            "assessment_status": source.assessment_status,
            "base_stage": source.base_stage,
            "card_week": selected_week.isoformat(),
            "card_source_age_bands": list(card_bands),
            "card_evidence": [{
                "source_age_band": row.source_age_band,
                "baseline_status": row.baseline_status,
                "v_ratio": row.v_ratio,
                "n_ratio": row.n_ratio,
                "v_stage": row.v_stage,
                "n_stage": row.n_stage,
                "alarm_stage": row.alarm_stage,
                "weak_threshold": row.weak_threshold,
                "strong_threshold": row.strong_threshold,
            } for row in evidence],
            "card_alarm_stage": alarm,
            "card_alarm_status": alarm_status,
            "stage_adjustment": int(strong and source.base_stage is not None),
            "final_stage": final_stage,
            "final_stage_label": STAGE_LABEL[final_stage] if final_stage is not None else source.source_stage_label,
            "priority_group": priority_group,
            "weakness_count": source.weakness_count,
            "population": source.population,
            "reason": source.reason,
            "structural_risk_ratio": source.structural_risk_ratio,
        })

    result.sort(key=lambda row: (
        row["final_stage"] if row["final_stage"] is not None else row["source_stage"],
        row["card_alarm_stage"] if row["card_alarm_stage"] is not None else -1,
        int(row["priority_group"] is not None),
        row["weakness_count"],
        row["population"],
    ), reverse=True)
    for rank, row in enumerate(result, start=1):
        row["priority_rank"] = rank
    return {
        "segments": result,
        "metadata": {
            "methodology_version": METHOD_VERSION,
            "workflow_version": WORKFLOW_VERSION,
            "input_schema_version": 4,
            "dataset_version": result[0]["dataset_version"],
            "selected_week": selected_week.isoformat(),
            "input_hash": digest({
                "segments": [row.model_dump(mode="json") for row in rows],
                "cards": [row.model_dump(mode="json") for row in cards if row.week == selected_week],
            }),
            "weekly_scope": "region × sex × source age band; not dong observations",
            "individual_diagnosis": False,
            "card_alarm_rule": "min(V, N); strong alone adds one to an assessed stage, capped at five",
            "priority_order": ["final_stage", "card_alarm_stage", "priority_group", "weakness_count", "population"],
            "priority_sort": "descending; stable source order breaks complete ties",
        },
    }
