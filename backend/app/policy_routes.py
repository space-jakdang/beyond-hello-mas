from fastapi import APIRouter,Query
from backend.policy.service import PolicyService,Search,Scope,SCOPES


def policy_router(settings):
    router=APIRouter(prefix='/policies');service=PolicyService(settings)
    @router.get('/coverage')
    def coverage():return service.coverage()
    @router.post('/refresh')
    def refresh():return service.refresh()
    @router.get('')
    def search(scopes:list[Scope]=Query(default=SCOPES,min_length=1,max_length=5),query:str=Query(default='',max_length=200),page:int=Query(default=1,ge=1,le=10000),per_page:int=Query(default=20,ge=1,le=100)):
        return service.search(Search(scopes=scopes,query=query,page=page,per_page=per_page))
    @router.get('/{policy_id}')
    def detail(policy_id:str):return service.detail(policy_id)
    return router
