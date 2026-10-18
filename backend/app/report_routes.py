import json
from uuid import UUID
from fastapi import APIRouter, HTTPException
from backend.app import config


def report_router(settings):
    router=APIRouter()
    def paths():
        root=config.ROOT/'eval'/('reports' if settings.data_mode=='sample' else 'local')
        return sorted(root.glob('*/*/summary.json'),reverse=True)

    @router.get('/reports')
    def reports():
        rows=[]
        for path in paths():
            try:
                body=json.loads(path.read_text())
                if body['data_mode']==settings.data_mode and body['llm_mode']==settings.llm_mode:
                    rows.append({key:body[key] for key in ('id','created_at','data_mode','llm_mode','status','evaluated_scenarios')})
            except (ValueError,KeyError):
                continue  # An unfinished or damaged file is never presented as a successful evaluation.
        return sorted(rows,key=lambda r:r['created_at'],reverse=True)[:100]

    @router.get('/reports/{report_id}')
    def report(report_id:UUID):
        for path in paths():
            if path.parent.name!=str(report_id):continue
            try:body=json.loads(path.read_text())
            except ValueError:raise HTTPException(409,'report incomplete or damaged')
            if body.get('data_mode')==settings.data_mode and body.get('llm_mode')==settings.llm_mode:
                return body
        raise HTTPException(404,'report not found in current data/LLM mode')
    return router
