from fastapi import APIRouter, HTTPException
from typing import Literal
from datetime import date
from backend.tools.neighborhoods import analysis, group_analysis


def analysis_router(settings):
    router=APIRouter()

    @router.get('/analysis')
    def get_analysis():
        try:return analysis(settings)
        except (OSError,ValueError,KeyError,TypeError):
            raise HTTPException(503,'분석 입력 또는 경계 데이터가 없거나 유효하지 않습니다. 서버 데이터 설정을 확인하세요.')
    @router.get('/analysis/groups')
    def get_groups(week: date | Literal['all'] | None=None, card_age: Literal['20s','30s','all']='20s',
                   workflow_version: Literal['regional-workflow-1','regional-workflow-2','current'] | None=None):
        version=workflow_version or 'regional-workflow-1'
        if version=='current':version='regional-workflow-2' if settings.data_mode=='local' else 'regional-workflow-1'
        try:
            if version=='regional-workflow-2':
                from backend.tools.neighborhoods import group_analysis_v4
                return group_analysis_v4(settings,week.isoformat() if isinstance(week,date) else None if week=='all' else week)
            return group_analysis(settings,week.isoformat() if isinstance(week,date) else week,card_age)
        except (OSError,ValueError,KeyError,TypeError):
            source='v4' if version=='regional-workflow-2' else 'v3'
            raise HTTPException(503,f'집단 분석 입력이 없거나 유효하지 않습니다. {source} 자료 반입을 확인하세요.')
    @router.get('/analysis/statistical-sources')
    def statistical_sources():
        from backend.tools.statistical_sources import readiness
        from backend.tools.segments_v3 import load_segments
        from backend.tools.region_stage import classify
        try:
            rows,source=load_segments(settings)
            assessment=classify([r for r in rows if r.preferred])
            assessment['data_mode']=settings.data_mode
            return readiness(assessment)
        except (OSError,ValueError,KeyError,TypeError):
            raise HTTPException(503,'통계 원천 자료를 확인할 수 없습니다.')
    return router
