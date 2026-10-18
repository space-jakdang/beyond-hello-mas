from fastapi import APIRouter, HTTPException
from backend.tools.neighborhoods import analysis


def analysis_router(settings):
    router=APIRouter()

    @router.get('/analysis')
    def get_analysis():
        try:return analysis(settings)
        except (OSError,ValueError,KeyError,TypeError):
            raise HTTPException(503,'분석 입력 또는 경계 데이터가 없거나 유효하지 않습니다. 서버 데이터 설정을 확인하세요.')
    return router
