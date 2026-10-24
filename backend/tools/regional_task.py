"""Versioned regional tasks. Local priorities are not individual diagnoses."""
from datetime import date
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.tools.indicators import digest
from backend.tools.region_stage import classify
from backend.tools.segments_v3 import load_segments

VERSION = 'regional-workflow-1'
STAGES = {1:'일반 관찰', 2:'변화 확인', 3:'추가 조사', 4:'우선 검토', 5:'집중 검토'}


class RegionalTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    methodology_version: Literal['regional-workflow-1'] = VERSION
    future_id: UUID | None = None
    sgg: Literal['11230','32010']
    ym: str = Field(pattern=r'^20\d{2}-(0[1-9]|1[0-2])$')
    as_of: date
    sex: Literal['M','F']
    age_group: Literal['youth','midlife','prime','elderly']
    dong_cd: str | None = Field(default=None, pattern=r'^\d{8}$')
    goal: str = Field(default='지역 신호와 통계를 검토하고 지원 자원을 제안하세요.', min_length=1, max_length=1000)

    @model_validator(mode='after')
    def scope(self):
        if self.dong_cd and not self.dong_cd.startswith(self.sgg):
            raise ValueError('dong outside task jurisdiction')
        if self.as_of.strftime('%Y-%m') < self.ym and self.future_id is None:
            raise ValueError('analysis date precedes observation month')
        return self


def task_from(payload):
    if payload.get('workflow_version') != VERSION:
        raise ValueError('unsupported regional workflow')
    return RegionalTask.model_validate(payload.get('task', {}))


def assess(settings, task, source_data=None):
    future=None
    if task.future_id:
        from backend.future import scenario_rows
        rows,source,future=scenario_rows(settings,task)
    else:
        rows, source = source_data if source_data is not None else load_segments(settings)
    selected = [r for r in rows if r.preferred and r.sgg == task.sgg and r.sex == task.sex
                and r.age_group == task.age_group and r.ym in (None, task.ym)
                and (task.dong_cd is None or r.dong_cd == task.dong_cd)]
    if not selected:
        raise ValueError('no observations for selected task')
    result = classify(selected)
    for row in result['segments']:
        if future and row['value'] is not None:
            from backend.tools.region_stage import youth_stage
            row['scenario_signals']=future['signals'][task.ym][row['dong_cd']]
            row['stage']=youth_stage(row['level_band'],row['scenario_signals'])
            row['scenario_stage']=row['stage']
        row['evidence_id'] = digest(row)
        row['stage_label'] = STAGES.get(row['stage'], '판정 보류')
    if future:
        for dong in result['dongs']:
            dong['stage']=max((r['stage'] for r in result['segments'] if r['dong_cd']==dong['dong_cd'] and r['stage'] is not None),default=None)
        result['metadata']['input_hash']=digest({'segments':result['segments'],'future_input_hash':future['input_hash']})
    return {**result, 'source_observations':[r.model_dump(mode='json') for r in rows if r.sgg==task.sgg and r.sex==task.sex and r.age_group==task.age_group and (r.ym is None or r.ym<=task.ym)], 'task': task.model_dump(mode='json'), 'methodology_version': VERSION,
            'data_mode': settings.data_mode, 'period_aggregate': any(r.ym is None for r in selected),
            'metadata': {**result['metadata'], 'analysis_version':'v3', 'workflow_version':VERSION,
                         'source':source,'review_contract_version':'statistics-review-2','matching_mode':'deterministic-regional-1', 'baseline_period_aggregate':future.get('baseline_period_aggregate') if future else None, 'synthetic_future':bool(future), 'provisional':True, 'card_signals_applied':False, 'synthetic_signals_applied':bool(future)}}
