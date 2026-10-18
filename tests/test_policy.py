import asyncio
import json
import shutil
import sys
from uuid import uuid4

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from backend.app.config import Settings, ROOT
from backend.policy.service import PolicyService, Search, SCOPES, jurisdiction


def rows():
    return [{'서비스ID':str(i),'서비스명':f'합성 정책 {i}','소관기관명':agency,'소관기관유형':kind,'지원대상':'합성 조건',
             '상세조회URL':'https://www.gov.kr/fixture'} for i,(agency,kind) in enumerate([
        ('보건복지부','중앙행정기관'),('서울특별시','지자체'),('서울특별시 강남구','지자체'),
        ('강원특별자치도','지자체'),('강원특별자치도 춘천시','지자체'),('경기도','지자체')])]


def provider(endpoint,params):
    selected=rows()[:3] if params['page']==1 else rows()[3:]
    return {'data':selected,'totalCount':6,'currentCount':len(selected)}


@pytest.fixture
def service(tmp_path,monkeypatch):
    import backend.app.config as config
    monkeypatch.setattr(config,'ROOT',tmp_path)
    return PolicyService(Settings(_env_file=None,gov24_service_key=None),provider)


def test_pages_scopes_and_atomic_failure(service):
    result=service.refresh()
    assert result['source_complete'] and list(result['scopes'].values())==[1]*5
    assert result['source_count']==6 and result['excluded_other_agencies']==1
    assert not result['all_policies_known']
    result=service.search(Search(per_page=2));assert result['total']==5 and result['next_page']==2
    assert len(service.search(Search(scopes=['chuncheon']))['items'])==1
    before=service.read('snapshot')
    service.fetch=lambda *args: {'data':rows()[:3],'totalCount':6,'currentCount':3}
    assert service.refresh()['last_attempt']['status']=='failed'
    assert service.read('snapshot')==before
    service.fetch=lambda *args: (_ for _ in ()).throw(RuntimeError('PRIVATE_SECRET'))
    assert 'PRIVATE_SECRET' not in json.dumps(service.refresh())
    service.fetch=service.request
    assert service.refresh()['last_attempt']['reason']=='missing_credentials'
    assert jurisdiction({'소관기관명':'서울특별시 강남구청소년센터'}) is None


@pytest.mark.parametrize('response',[
    {'data':[],'totalCount':1,'currentCount':0},
    {'data':rows(),'totalCount':2,'currentCount':6},
    {'data':rows(),'totalCount':6,'currentCount':5},
])
def test_bad_pages_never_publish(service,response):
    service.fetch=lambda *args:response
    assert service.refresh()['status']=='unavailable'


def test_live_detail_and_mismatched_filter(service):
    service.refresh()
    def detail(endpoint,params):
        assert params['cond[서비스ID::EQ]']=='0'
        return {'data':[rows()[0]] if endpoint=='serviceDetail' else [{'서비스ID':'0','JA0101':'Y'}]}
    service.fetch=detail
    result=service.detail('0')
    assert result['status']=='live' and result['conditions']['JA0101']=='Y'
    assert result['policy']['remaining_capacity'] is None and not result['policy']['eligibility_verified']
    service.fetch=lambda *args:{'data':[rows()[1]]}
    assert service.detail('0')['status']=='cached'
    assert service.detail('outside')['status']=='not_found'


def test_real_mcp_stdio_roundtrip():
    settings=Settings(_env_file=None,evaluation_id=uuid4(),gov24_service_key=None)
    service=PolicyService(settings,provider);service.refresh()
    async def invoke():
        parameters=StdioServerParameters(command=sys.executable,args=['-m','backend.policy.server'],cwd=str(ROOT),
            env={'DATA_MODE':'sample','LLM_MODE':'fake','EVALUATION_ID':str(settings.evaluation_id),'GOV24_SERVICE_KEY':''})
        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                names={t.name for t in (await session.list_tools()).tools}
                assert names=={'policy_coverage','policy_refresh','policy_search','policy_detail'}
                result=await session.call_tool('policy_search',{'scopes':SCOPES,'per_page':2})
                assert not result.is_error and result.structured_content['total']==5
                invalid=await session.call_tool('policy_search',{'scopes':['unsupported']})
                assert invalid.is_error
                missing=await session.call_tool('policy_refresh',{})
                assert missing.structured_content['last_attempt']['reason']=='missing_credentials'
    try:asyncio.run(asyncio.wait_for(invoke(),20))
    finally:shutil.rmtree(settings.runtime_dir)


def test_rest_validation_and_missing_credentials(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.policy_routes import policy_router
    app=FastAPI();app.include_router(policy_router(service.settings))
    with TestClient(app) as client:
        assert client.get('/policies').json()['total']==0
        assert client.get('/policies?scopes=unknown').status_code==422
        assert client.get('/policies?per_page=0').status_code==422
        assert client.post('/policies/refresh').json()['last_attempt']['reason']=='missing_credentials'
        assert client.get('/policies/unknown').json()['status']=='not_found'


def test_page_limit_and_changed_total_preserve_previous(service):
    service.refresh();before=service.read('snapshot')
    service.settings.policy_max_pages=1
    assert service.refresh()['last_attempt']['status']=='failed'
    service.settings.policy_max_pages=30
    def changed(endpoint,params):
        body=provider(endpoint,params)
        if params['page']==2:body['totalCount']=7
        return body
    service.fetch=changed
    assert service.refresh()['last_attempt']['status']=='failed'
    assert service.read('snapshot')==before


def test_key_header_redaction_and_redirect(service,monkeypatch):
    from pydantic import SecretStr
    from urllib.error import HTTPError
    from backend.policy.service import NoRedirect
    import backend.policy.service as module
    service.settings.gov24_service_key=SecretStr('SECRET%2BVALUE%3D')
    service.fetch=service.request
    class Opener:
        def open(self,request,timeout):
            assert 'SECRET' not in request.full_url and 'serviceKey' not in request.full_url
            assert request.get_header('Authorization')=='Infuser SECRET+VALUE='
            raise HTTPError(request.full_url,401,'SECRET',{},None)
    monkeypatch.setattr(module,'build_opener',lambda handler:Opener())
    assert 'SECRET' not in json.dumps(service.refresh())
    with pytest.raises(ValueError,match='redirect'):
        NoRedirect().redirect_request(None,None,None,None,None,None)
