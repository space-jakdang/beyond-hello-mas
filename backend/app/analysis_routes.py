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
    def get_groups(week: date | Literal['all'] | None=None, card_age: Literal['20s','30s','all']='20s'):
        try:return group_analysis(settings,week.isoformat() if isinstance(week,date) else week,card_age)
        except (OSError,ValueError,KeyError,TypeError):
            raise HTTPException(503,'집단 분석 입력이 없거나 유효하지 않습니다. v3 자료 반입을 확인하세요.')
    return router
