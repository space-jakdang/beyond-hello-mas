import csv

import pytest

from backend.app.config import Settings
from backend.tools.neighborhoods import group_analysis_v4
from scripts.check_regional_release import check, compare_priority_table
from tests.test_runtime_package_v2 import catalog_package, v2_package


def test_v2_acceptance_compares_all_priority_cells_and_unassessed_stages(v2_package, tmp_path):
    settings = Settings(_env_file=None, data_mode='local', input_root=v2_package,
                        regional_workflow_version='regional-workflow-2', resource_catalog='v3',
                        llm_mode='fake')
    segments = group_analysis_v4(settings)['segments']
    path = tmp_path / 'priority.csv'
    fields = ['순위', '지역', '행정동', '성', '연령대', '틀', '단계명',
              '카드경보', '최종단계', '최종단계명']
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in segments:
            writer.writerow({
                '순위': row['priority_rank'], '지역': row['source_region'],
                '행정동': row['source_dong_name'], '성': '남' if row['sex'] == 'M' else '여',
                '연령대': row['source_age_band'], '틀': row['frame'],
                '단계명': row['source_stage_label'],
                '카드경보': '' if row['card_alarm_stage'] is None else {0: '없음', 1: '약', 2: '강'}[row['card_alarm_stage']],
                '최종단계': row['source_stage'] if row['final_stage'] is None else row['final_stage'],
                '최종단계명': row['final_stage_label'],
            })
    assert compare_priority_table(segments, path) == 514
    assert any(row['assessment_status'] == 'small_population_hold' and row['final_stage'] is None for row in segments)
    assert any(row['assessment_status'] == 'insufficient_evidence' and row['final_stage'] is None for row in segments)

    with path.open(encoding='utf-8', newline='') as stream:
        records = list(csv.DictReader(stream))
    records[0]['순위'] = str(int(records[0]['순위']) + 1)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    with pytest.raises(ValueError, match='priority reference mismatch'):
        compare_priority_table(segments, path)


def test_v2_acceptance_requires_source_delivery(v2_package):
    with pytest.raises(ValueError, match='original source delivery'):
        check(v2_package)
