import json
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, HTTPException
from backend.app import config
from backend.app.quality_reports import quality_detail, quality_list


def report_router(settings):
    router=APIRouter()
    def modes(source):
        return ('sample','fake') if source=='sample' else (settings.data_mode,settings.llm_mode)
    def paths(source):
        root=config.ROOT/'eval'/('reports' if modes(source)[0]=='sample' else 'local')
        return sorted(root.glob('*/*/summary.json'),reverse=True)

    @router.get('/reports')
    def reports(source:Literal['current','sample']='current'):
        rows=[]
        for path in paths(source):
            try:
                body=json.loads(path.read_text())
                if (body['data_mode'],body['llm_mode'])==modes(source):
                    rows.append({**{key:body[key] for key in ('id','created_at','data_mode','llm_mode','status','evaluated_scenarios')},'schema_version':body.get('schema_version','1')})
            except (ValueError,KeyError):
                continue  # An unfinished or damaged file is never presented as a successful evaluation.
        return sorted(rows,key=lambda r:r['created_at'],reverse=True)[:100]

    @router.get('/reports/quality')
    def quality_reports(source:Literal['current','sample']='current'):
        return quality_list(settings, source)

    @router.get('/reports/quality/{report_id}')
    def quality_report(report_id:UUID, source:Literal['current','sample']='current',
                       region:str|None=None, period:str|None=None, methodology:str|None=None, observation_source:Literal['observed','synthetic']|None=None):
        return quality_detail(settings, source, report_id, region, period, methodology, observation_source)

    @router.get('/reports/{report_id}')
    def report(report_id:UUID,source:Literal['current','sample']='current'):
        for path in paths(source):
            if path.parent.name!=str(report_id):continue
            try:body=json.loads(path.read_text())
            except ValueError:raise HTTPException(409,'report incomplete or damaged')
            if (body.get('data_mode'),body.get('llm_mode'))==modes(source):
                return body
        raise HTTPException(404,'report not found in current data/LLM mode')
    return router
