"""Read-only deployment diagnostics; never expose paths, keys, or source records."""
import os
import sqlite3
from fastapi import APIRouter
from backend.tools.neighborhoods import group_analysis
from backend.tools.catalog import load_catalog


def inspect(settings):
    temporary = os.getenv('VERCEL') == '1' and settings.runtime_storage_root is None
    result = {'data_mode': settings.data_mode, 'llm_mode': settings.llm_mode,
              'storage': 'temporary_instance' if temporary else 'configured_directory' if settings.runtime_storage_root else 'local_directory',
              'single_instance_required': True, 'durability_verified': False,
              'analysis': {'status': 'unavailable', 'reason': 'analysis_inputs_missing_or_invalid'},
              'catalog': {'status': 'unavailable', 'reason': 'catalog_missing_or_invalid'}, 'warnings': []}
    configured=bool(settings.kosis_api_key and settings.kosis_api_key.get_secret_value().strip())
    result['regional_context']={'provider':'synthetic_fixture' if settings.data_mode=='sample' else 'kosis',
        'status':'synthetic_fixture' if settings.data_mode=='sample' else 'not_checked' if configured else 'credentials_missing',
        'credentials_configured':configured,'reference_year':settings.regional_reference_year}
    if settings.data_mode=='local' and configured:
        from backend.context.service import ContextService
        try:
            attempt=ContextService(settings).last_attempt()
            if attempt and attempt['data_mode']=='local' and attempt['request']['reference_year']==settings.regional_reference_year:
                from datetime import datetime,timezone
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(attempt['at'])).total_seconds()
                if attempt['status'] not in ('ready','partial','unavailable'):raise ValueError('invalid history status')
                result['regional_context']['last_attempt']=attempt
                if 0<=age<86400:
                    result['regional_context'].update(status=attempt['status'],scope='last_requested_region')
        except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):
            result['regional_context']['reason']='history_inputs_missing_or_invalid'
    if settings.data_mode == 'sample':
        result['warnings'].append('합성 데이터 모드입니다. 실제 동·지도는 승인된 실제 자료와 DATA_MODE=local 설정이 필요합니다.')
    if temporary:
        result['warnings'].append('이 서버는 인스턴스별 임시 저장소를 사용합니다. 재배포·인스턴스 변경 후 실행 이력이 사라질 수 있습니다.')
    try:
        data = group_analysis(settings, week='all', card_age='all')
        coverage = data['coverage']
        result['analysis'] = {'status': 'ready' if not coverage['unmatched_codes'] else 'incomplete_geometry',
                              'synthetic': settings.data_mode == 'sample',
                              'neighborhood_count': len(data['neighborhoods']), 'coverage': coverage,
                              'geometry': 'synthetic_grid' if settings.data_mode == 'sample' else 'administrative_boundaries'}
    except Exception:
        pass
    try:
        load_catalog(settings.catalog_path)
        result['catalog'] = {'status': 'ready', 'version': settings.resource_catalog}
    except Exception:
        pass
    result['ready'] = result['analysis']['status'] == 'ready' and result['catalog']['status'] == 'ready'
    return result


def readiness_router(settings):
    router = APIRouter()
    @router.get('/readiness')
    def readiness():
        return inspect(settings)
    return router
