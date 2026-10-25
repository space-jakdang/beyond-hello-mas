import json
import sqlite3
import io
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from urllib.error import HTTPError,URLError
from urllib.parse import parse_qs,urlsplit

import pytest

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.context.contracts import ContextRequest
from backend.context.service import ContextService,ContextUnavailable,TABLE
from backend.tools.indicators import digest


def settings(tmp_path,**changes):
    return Settings(_env_file=None,data_mode='local',llm_mode='fake',runtime_storage_root=tmp_path,
                    **{'kosis_api_key':'generated-secret',**changes})


def request():
    return ContextRequest(sgg='11230',dong_cd='11230510',reference_year=2020,as_of='2026-10-24')


def rows():
    return [{'ORG_ID':'101','TBL_ID':TABLE,'PRD_SE':'A','PRD_DE':'2020','C1':'11230510','C1_NM':'신사동',
             'ITM_ID':item,'ITM_NM':name,'DT':value,'UNIT_NM':unit} for item,name,value,unit in
            [('T100','총인구','1,200','명'),('T200','가구_계','600','가구'),('T310','주택_계','650','호')]]


# /ship Step 7 value card
# Value: protects=cache entries remain scoped to the requested year and recover after corruption;
# fails_when=wrong-key or invalid cached rows become observed facts or poison later requests;
# why_new=existing checksum assertion did not assert eviction, recovery or valid-hash replay rejection;
# seam=none; no_claim=generated provider rows and local SQLite; no live KOSIS acceptance.
def test_real_profile_is_partial_source_typed_and_cache_is_verified(tmp_path):
    calls=[]
    def fetch(endpoint,args):
        calls.append((endpoint,args))
        result=rows()
        for row in result:row['PRD_DE']=args['startPrdDe']
        result[0]['DT']=f"{1200+100*(int(args['startPrdDe'])-2020):,}"
        return result
    service=ContextService(settings(tmp_path),fetch)
    first=service.profile(request());second=service.profile(request())
    assert first==second and len(calls)==5 and first['status']=='partial'
    assert first['source']=='kosis' and first['data_mode']=='local'
    assert next(f for f in first['facts'] if f['metric']=='total_population')['value']==1200
    assert next(f for f in first['facts'] if f['metric']=='youth_population')['value'] is None
    assert all('apiKey' not in f['source_url'] for f in first['facts'])
    with sqlite3.connect(service.path) as db:
        key,body=db.execute('SELECT key,body FROM context_cache').fetchone()
        changed=json.loads(body);changed['rows'][0]['DT']='999'
        db.execute('UPDATE context_cache SET body=? WHERE key=?',(json.dumps(changed),key))
    assert service.profile(request())['status']=='unavailable'
    with sqlite3.connect(service.path) as db:
        assert db.execute('SELECT COUNT(*) FROM context_cache').fetchone()[0]==0
    assert service.profile(request())['status']=='partial'
    with sqlite3.connect(service.path) as db:
        original=json.loads(db.execute('SELECT body FROM context_cache').fetchone()[0])
    next_year=request().model_copy(update={'reference_year':2021})
    assert service.profile(next_year)['status']=='partial'
    with sqlite3.connect(service.path) as db:
        saved=[json.loads(row[0]) for row in db.execute('SELECT body FROM context_cache')]
    current=next(s for s in saved if s['rows'][0]['PRD_DE']=='2021')
    for corruption in ('replayed_body','json','year','table','organization','period'):
        altered=json.loads(json.dumps(current))
        if corruption=='replayed_body':altered=original
        elif corruption!='json':
            field,value={'year':('PRD_DE','2020'),'table':('TBL_ID','other'),
                         'organization':('ORG_ID','other'),'period':('PRD_SE','M')}[corruption]
            altered['rows'][0][field]=value
            altered['source_hash']=digest(altered['rows'])
        with sqlite3.connect(service.path) as db:
            db.execute('UPDATE context_cache SET body=? WHERE key=?',
                       ('{' if corruption=='json' else json.dumps(altered),current['cache_key']))
        rejected=service.profile(next_year)
        assert rejected['status']=='unavailable',corruption
        assert rejected['facts']==[],corruption
        with sqlite3.connect(service.path) as db:
            assert db.execute('SELECT body FROM context_cache WHERE key=?',(current['cache_key'],)).fetchone() is None
        recovered=service.profile(next_year)
        assert recovered['status']=='partial',corruption
        population=next(f for f in recovered['facts'] if f['metric']=='total_population')
        assert (population['reference_year'],population['value'])==(2021,1300),corruption
    future={**current,'fetched_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
    with sqlite3.connect(service.path) as db:
        db.execute('UPDATE context_cache SET body=? WHERE key=?',(json.dumps(future),current['cache_key']))
    before=sum(args['tblId']==TABLE for _,args in calls)
    assert service.profile(next_year)['status']=='partial'
    assert sum(args['tblId']==TABLE for _,args in calls)==before+1


def test_missing_credentials_and_provider_errors_never_become_synthetic(tmp_path):
    missing=ContextService(settings(tmp_path,kosis_api_key=None)).profile(request())
    assert missing['status']=='unavailable' and missing['reason']=='missing_credentials'
    assert missing['data_mode']=='local' and missing['facts']==[]
    def fetch(*args):raise ValueError('do not expose generated-secret')
    failed=ContextService(settings(tmp_path),fetch).profile(request())
    assert failed['status']=='unavailable' and 'generated-secret' not in json.dumps(failed)
    for index,changes in enumerate(({'TBL_ID':'other'},{'PRD_DE':'2030'},{'UNIT_NM':'%'},{'DT':'NaN'},{'C1_NM':'다른 동'})):
        def invalid(*args):return [{**r,**changes} for r in rows()]
        service=ContextService(settings(tmp_path/str(index)),invalid)
        assert service.profile(request())['status']=='unavailable'


# /ship Step 7 value card
# Value: protects=the regional API validates scope/date inputs and connects configured local transport to partial profiles;
# fails_when=year/date defaults, error mapping or route-to-provider/cache wiring drift;
# why_new=existing local HTTP requests stop at missing credentials and never assert forwarded dates;
# seam=none; no_claim=generated transport and sample data; no live provider or browser verification.
# Pass2: unknown local dongs must stop before fetch; corrupt cached policy data
# must leave the HTTP census response and independently valid catalog usable.
def test_profile_api_is_synthetic_only_in_explicit_sample_mode(tmp_path,monkeypatch):
    local=settings(tmp_path,kosis_api_key=None)
    with TestClient(create_app(local)) as client:
        assert client.get('/analysis/regional-context?sgg=11230&dong_cd=32010001').status_code==422
        assert client.get('/analysis/regional-context?sgg=11230&dong_cd=11230510&reference_year=0').status_code==422
        report=client.get('/analysis/regional-context?sgg=11230&dong_cd=11230510').json()
        assert report['data_mode']=='local' and report['status']=='unavailable'
    sample=Settings(_env_file=None,data_mode='sample',llm_mode='fake',runtime_storage_root=tmp_path/'sample')
    with TestClient(create_app(sample)) as client:
        report=client.get('/analysis/regional-context?sgg=11230&dong_cd=11230001').json()
        assert report['data_mode']=='sample' and report['source']=='synthetic_fixture'
        assert len(report['facts'])==9 and report['status']=='ready'
        assert client.get('/analysis/regional-context?sgg=11230&dong_cd=11230001').json()['input_hash']==report['input_hash']
        assert client.get('/analysis/regional-context?sgg=11230&dong_cd=11230999').status_code==422
    import backend.context.service as module
    class Clock(datetime):
        @classmethod
        def now(cls,tz):return datetime(2025,12,31,16,tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(module,'datetime',Clock)
    with TestClient(create_app(local)) as client:
        default=client.get('/analysis/regional-context?sgg=11230&dong_cd=11230510').json()
        assert default['request']['as_of']=='2026-01-01'
        assert default['request']['reference_year']==2020
        earlier=client.get('/analysis/regional-context?sgg=11230&dong_cd=11230510&as_of=2019-12-31').json()
        assert earlier['request']['reference_year']==2019
        assert client.get('/analysis/regional-context?sgg=11230&dong_cd=11230510&reference_year=2021&as_of=2020-01-01').status_code==422
        assert client.get('/analysis/regional-context?sgg=11230&dong_cd=11230510&as_of=invalid').status_code==422
    calls=[]
    def open_request(sent,timeout):
        query=parse_qs(urlsplit(sent.full_url).query);calls.append(query)
        if query['tblId']!=[TABLE]:raise URLError('generated-secret')
        result=rows()
        for row in result:row['PRD_DE']=query['startPrdDe'][0]
        return io.BytesIO(json.dumps(result).encode())
    monkeypatch.setattr(module,'build_opener',lambda handler:SimpleNamespace(open=open_request))
    configured=settings(tmp_path/'configured',input_root=tmp_path/'configured-inputs')
    from backend.app.config import ROOT
    from backend.policy.service import PolicyService
    configured.catalog_path.parent.mkdir(parents=True)
    configured.catalog_path.write_bytes((ROOT/'data/sample/resources.csv').read_bytes())
    with TestClient(create_app(configured)) as client:
        assert client.get('/analysis/regional-context?sgg=11230&dong_cd=11230999').status_code==422
        assert calls==[]
        url='/analysis/regional-context?sgg=11230&dong_cd=11230510&reference_year=2020&as_of=2021-04-05'
        report=client.get(url).json()
        assert report['status']=='partial' and report['source']=='kosis'
        assert report['request']=={'schema_version':'1','sgg':'11230','dong_cd':'11230510','reference_year':2020,'as_of':'2021-04-05'}
        assert next(f for f in report['facts'] if f['metric']=='total_population')['value']==1200
        assert client.get(url).json()['input_hash']==report['input_hash']
        assert len(calls)==5 and all(q['startPrdDe']==q['endPrdDe']==['2020'] for q in calls)
        assert 'generated-secret' not in json.dumps(report)
        catalog=report['resources']['catalog']
        assert catalog['status']=='available' and catalog['total']==6
        policies=PolicyService(configured)
        for malformed in ('{','[{}]','{"policies":[{}]}','{"policies":"invalid"}'):
            with sqlite3.connect(policies.path) as db:
                db.execute('INSERT OR REPLACE INTO policy_state VALUES (?,?)',('snapshot',malformed))
            response=client.get(url)
            assert response.status_code==200
            recovered=response.json()
            assert recovered['status']=='partial'
            assert next(f for f in recovered['facts'] if f['metric']=='total_population')['value']==1200
            assert recovered['resources']['catalog']==catalog
            assert recovered['resources']['policies']=={'items':[],'total':None,
                'coverage':{'status':'unavailable','reason':'cached_policy_inputs_missing_or_invalid'}}
            assert 'generated-secret' not in json.dumps(recovered)
        policies.path.write_bytes(b'generated invalid SQLite file')
        response=client.get(url)
        assert response.status_code==200
        recovered=response.json()
        assert next(f for f in recovered['facts'] if f['metric']=='total_population')['value']==1200
        assert recovered['resources']['catalog']==catalog
        assert recovered['resources']['policies']['coverage']['status']=='unavailable'
        assert sum(q['tblId']==[TABLE] for q in calls)==1
    for year in (1999,2101):
        with pytest.raises(ValueError):Settings(_env_file=None,llm_mode='fake',regional_reference_year=year)
    monkeypatch.setenv('REGIONAL_REFERENCE_YEAR','2021')
    monkeypatch.setenv('KOSIS_API_KEY','generated-env-secret')
    env=Settings(_env_file=None,llm_mode='fake')
    assert env.regional_reference_year==2021 and env.kosis_api_key.get_secret_value()=='generated-env-secret'
    assert 'generated-env-secret' not in repr(env)


# /ship Step 7 value card
# Value: protects=bounded request history, region-scoped cached resources and truthful readiness diagnostics;
# fails_when=history grows unbounded, resources cross districts or stale/mismatched attempts imply readiness;
# why_new=existing test checks only missing/configured key status and not the new history/resource boundaries;
# seam=none; no_claim=generated catalog/policy snapshots and SQLite; no live inventory, eligibility or deployment proof.
# Pass2: malformed persisted history must produce a recoverable HTTP diagnostic,
# including invalid schema, timestamp and status without leaking cache contents.
def test_readiness_does_not_treat_a_configured_key_as_verified_statistics(tmp_path,monkeypatch):
    from backend.app.readiness import inspect
    from backend.app.config import ROOT
    from backend.policy.service import PolicyService,SCOPES
    for key,status in ((None,'credentials_missing'),('generated-secret','not_checked')):
        report=inspect(settings(tmp_path,kosis_api_key=key))
        assert report['regional_context']['status']==status
        assert 'generated-secret' not in json.dumps(report)
    cfg=settings(tmp_path/'history',input_root=tmp_path/'inputs')
    cfg.catalog_path.parent.mkdir(parents=True)
    cfg.catalog_path.write_bytes((ROOT/'data/sample/resources.csv').read_bytes())
    policies=PolicyService(cfg)
    policies.write(snapshot={'fetched_at':datetime.now(timezone.utc).isoformat(),'source_complete':True,
        'source_count':5,'excluded_other_agencies':0,'policies':[
            {'id':scope,'scope':scope,'title':scope,'summary':'fixture','support':'fixture',
             'eligibility':'unverified','agency':scope,'criteria':''} for scope in SCOPES]})
    def no_network(*args):raise AssertionError('cached resources must not fetch from a provider')
    monkeypatch.setattr(PolicyService,'request',no_network)
    service=ContextService(cfg,lambda endpoint,args:rows())
    for context,expected_catalog,expected_policies in (
        (request(),{'synthetic-01','synthetic-02','synthetic-03','synthetic-06','synthetic-07','synthetic-08'},
         {'central','seoul','gangnam'}),
        (request().model_copy(update={'sgg':'32010','dong_cd':'32010110'}),
         {'synthetic-01','synthetic-04','synthetic-05','synthetic-06','synthetic-07','synthetic-09'},
         {'central','gangwon','chuncheon'})):
        resources=service.resources(context)
        assert resources['catalog']['status']=='available'
        assert {r['id'] for r in resources['catalog']['items']}==expected_catalog
        assert resources['catalog']['total']==6
        assert resources['catalog']['input_hash']==digest(resources['catalog']['items'])
        assert {p['id'] for p in resources['policies']['items']}==expected_policies
        assert resources['policies']['coverage']['status']=='cached'
        assert resources['policies']['coverage']['all_policies_known'] is False
        assert resources['limitation']
    before=inspect(cfg)
    profile=service.profile(request())
    attempt=service.last_attempt()
    assert attempt['request']==profile['request'] and attempt['input_hash']==profile['input_hash']
    assert attempt['source_hashes']==sorted({f['source_hash'] for f in profile['facts']})
    assert set(attempt)=={'request','source','data_mode','status','reason','input_hash','at','source_hashes'}
    after=inspect(cfg)
    assert after['regional_context']['status']=='partial'
    assert after['regional_context']['scope']=='last_requested_region'
    assert after['regional_context']['last_attempt']==attempt
    assert after['ready']==before['ready']
    assert 'generated-secret' not in json.dumps(after)
    for at,year in ((datetime.now(timezone.utc)-timedelta(days=2),2020),
                    (datetime.now(timezone.utc)+timedelta(days=1),2020),
                    (datetime.now(timezone.utc),2021)):
        changed={**attempt,'at':at.isoformat(),'request':{**attempt['request'],'reference_year':year}}
        with sqlite3.connect(service.path) as db:
            db.execute('UPDATE context_history SET body=?',(json.dumps(changed),))
        stale=inspect(cfg)['regional_context']
        assert stale['status']=='not_checked' and 'scope' not in stale
        assert ('last_attempt' in stale)==(year==2020)
    with TestClient(create_app(cfg)) as client:
        for malformed in ('{','[]','{}','[{}]',json.dumps({'data_mode':'local'}),
                          json.dumps({**attempt,'at':'2026-01-01T00:00:00'}),
                          json.dumps({**attempt,'status':'generated-invalid-status'})):
            with sqlite3.connect(service.path) as db:
                db.execute('UPDATE context_history SET body=?',(malformed,))
            response=client.get('/readiness')
            assert response.status_code==200
            diagnostic=response.json()['regional_context']
            assert diagnostic['status']=='not_checked' and 'scope' not in diagnostic
            assert diagnostic['reason']=='history_inputs_missing_or_invalid'
            assert 'last_attempt' not in diagnostic
            assert 'generated-invalid-status' not in response.text and 'generated-secret' not in response.text
    for _ in range(501):service.finish({k:v for k,v in profile.items() if k!='input_hash'})
    with sqlite3.connect(service.path) as db:
        assert db.execute('SELECT COUNT(*) FROM context_history').fetchone()[0]==500
        oldest,newest=db.execute('SELECT MIN(id),MAX(id) FROM context_history').fetchone()
        assert newest-oldest==499 and oldest>1
    assert service.last_attempt()['input_hash']==profile['input_hash']
    cfg.catalog_path.unlink()
    assert service.resources(request())['catalog']=={'status':'unavailable','items':[],'total':None}
    sample=Settings(_env_file=None,data_mode='sample',llm_mode='fake',runtime_storage_root=tmp_path/'sample',kosis_api_key=' ')
    assert inspect(sample)['regional_context']=={'provider':'synthetic_fixture','status':'synthetic_fixture',
        'credentials_configured':False,'reference_year':2020}


def test_invalid_snapshot_is_not_retained_and_expired_snapshot_is_refetched(tmp_path):
    from datetime import datetime,timedelta,timezone
    calls=[]
    def fetch(*args):
        if args[1]['tblId']!=TABLE:raise ValueError('optional source unavailable')
        calls.append(1)
        return [{**r,'UNIT_NM':'%'} for r in rows()] if len(calls)==1 else rows()
    service=ContextService(settings(tmp_path),fetch)
    assert service.profile(request())['status']=='unavailable'
    assert service.profile(request())['status']=='partial' and len(calls)==2
    with sqlite3.connect(service.path) as db:
        key,body=db.execute('SELECT key,body FROM context_cache').fetchone();snapshot=json.loads(body)
        snapshot['fetched_at']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        db.execute('UPDATE context_cache SET body=? WHERE key=?',(json.dumps(snapshot),key))
    assert service.profile(request())['status']=='partial' and len(calls)==3


# /ship Step 7 value card
# Value: protects=independent source facts survive optional failures and population alignment requires observed equal totals;
# fails_when=malformed optional rows discard good facts, missing totals align or unsupported source hashes borrow observations;
# why_new=existing optional-table fixture covers only complete valid counts and equal observed totals;
# seam=none; no_claim=generated census tables; source truth, live periods and policy quality remain unverified.
# Pass2: wrong optional geography and unrequested categories/dimensions cannot
# invalidate independent core observations or force healthy core-cache refetches.
def test_optional_census_tables_preserve_general_households_and_exact_youth_ranges(tmp_path):
    case='valid';base_calls=[]
    def fetch(endpoint,args):
        table=args['tblId']
        if table==TABLE:
            base_calls.append(case)
            if case=='base-unavailable':raise ContextUnavailable('provider_connection_failed')
            result=rows()
            if case in ('totals-missing','base-total-missing'):result[0]['DT']='-'
            if case=='fractional-households-new-base':result[0]['DT']='1,300'
        base={'ORG_ID':'101','TBL_ID':table,'PRD_SE':'A','PRD_DE':'2020','C1':'11230510','C1_NM':'신사동'}
        if table=='DT_1JC1502':
            result=[{**base,'ITM_ID':item,'ITM_NM':name,'UNIT_NM':'가구','DT':value} for item,name,value in [('T0','일반가구_계','550'),('T1','1인','200')]]
            if case.startswith('fractional-households'):result[1]['DT']='200.5'
            if case=='household-unit':result[1]['UNIT_NM']='호'
            if case=='negative-households':result[1]['DT']='-1'
            if case=='bool-households':result[1]['DT']=True
            if case=='duplicate-households':result.append(dict(result[1]))
            if case=='unknown-household-item':result[1]['ITM_ID']='unexpected'
            if case=='wrong-household-name':result[1]['C1_NM']='개포3동'
            if case=='wrong-household-code':result[1]['C1']='11230999'
            if case=='household-scalar-category':result[1]['C2']='unexpected'
            if case.startswith('household-extra-dimension-'):result[1]['C'+case.rsplit('-',1)[1]]='unexpected'
        elif table=='DT_1IN1503':
            result=[{**base,'ITM_ID':'T00','C2':age,'UNIT_NM':'명','DT':value} for age,value in [('000','1200'),('020005','10'),('025','100'),('030','110'),('035','120'),('104','150')]]
            if case in ('totals-missing','age-total-missing'):result[0]['DT']='-'
            if case=='different-total':result[0]['DT']='1300'
            if case=='incomplete-youth':result=[r for r in result if r['C2']!='035']
            if case=='age-unrequested-category':result[1]['C2']='999'
            if case=='age-extra-dimension':result[1]['C3']='unexpected'
        if case=='all-missing':
            for row in result:row['DT']='-'
        return result
    report=ContextService(settings(tmp_path),fetch).profile(request())
    by={f['metric']:f for f in report['facts']}
    assert by['general_households']['value']==550 and by['total_households']['value']==600
    assert by['youth_population']['value']==340 and by['youth_population']['source_dimensions']==['020005','025','030','035']
    assert by['senior_population']['value']==150 and by['senior_population']['sex']=='all'
    assert by['one_person_households']['population']==by['general_households']['population']!=by['total_households']['population']
    assert by['youth_population']['population']==by['total_population']['population']
    assert by['population_density']['value'] is None
    assert by['general_households']['source_table']=='DT_1JC1502'
    assert by['general_households']['source_items']==['T0']
    for metric in ('population_density','average_age'):
        assert by[metric]['source_table'] is None and by[metric]['source_items']==by[metric]['source_dimensions']==[]
        assert by[metric]['reason']=='metric_not_configured'
        assert by[metric]['source_hash']==digest({'metric':metric,'status':'not_configured'})
    missing_hash=None;base_hash=None
    for case in ('fractional-households','household-unit','negative-households','bool-households',
                 'duplicate-households','unknown-household-item','fractional-households-new-base',
                 'base-unavailable','totals-missing','base-total-missing','age-total-missing',
                 'different-total','incomplete-youth','all-missing',
                 'wrong-household-name','wrong-household-code','household-scalar-category',
                 'household-extra-dimension-3','household-extra-dimension-8',
                 'age-unrequested-category','age-extra-dimension'):
        service=ContextService(settings(tmp_path/case),fetch)
        report=service.profile(request());facts={f['metric']:f for f in report['facts']}
        assert report['status']==('unavailable' if case=='all-missing' else 'partial'),case
        if case=='all-missing':
            assert report['reason']=='no_observed_metrics' and all(f['value'] is None for f in facts.values())
        elif case=='base-unavailable':
            assert facts['total_population']['value'] is None
            assert facts['total_population']['reason']=='provider_connection_failed'
            assert facts['general_households']['value']==550 and facts['youth_population']['value']==340
        elif case in ('totals-missing','base-total-missing','age-total-missing','different-total'):
            assert facts['youth_population']['value']==340 and facts['senior_population']['value']==150
            assert facts['youth_population']['population']==facts['senior_population']['population']=='census_residents_age_table'
        elif case=='incomplete-youth':
            assert facts['youth_population']['value'] is None and facts['senior_population']['value']==150
        elif case in ('wrong-household-name','wrong-household-code','household-scalar-category',
                      'household-extra-dimension-3','household-extra-dimension-8',
                      'age-unrequested-category','age-extra-dimension'):
            metric='youth_population' if case.startswith('age-') else 'one_person_households'
            assert facts['total_population']['value']==1200
            assert facts[metric]['value'] is None and facts[metric]['status']=='missing'
            expected='provider_geography_mismatch' if case.startswith('wrong-') else 'provider_scope_mismatch'
            assert facts[metric]['reason']==expected
            before=base_calls.count(case)
            assert service.profile(request())['status']=='partial'
            assert base_calls.count(case)==before,case
        else:
            assert facts['total_population']['value']==(1300 if case.endswith('new-base') else 1200)
            assert facts['one_person_households']['status']=='missing'
            assert facts['one_person_households']['reason'] in ('provider_invalid_count','provider_unit_mismatch',
                'provider_inputs_missing_or_invalid','provider_duplicate_observation','provider_scope_mismatch')
            before=base_calls.count(case)
            assert service.profile(request())['status']=='partial'
            assert base_calls.count(case)==before,case
            if case=='fractional-households':
                missing_hash=facts['one_person_households']['source_hash'];base_hash=facts['total_population']['source_hash']
            elif case=='fractional-households-new-base':
                assert facts['one_person_households']['source_hash']==missing_hash
                assert facts['total_population']['source_hash']!=base_hash


# /ship Step 7 value card
# Value: protects=fixed-origin bounded KOSIS transport, decoder admission and secret-free error codes;
# fails_when=endpoint/key guards, wire parameters, byte/row limits or exception sanitization drift;
# why_new=all previous context fixtures bypass the request method;
# seam=none; no_claim=generated urllib responses/errors; no live authentication or provider acceptance.
def test_request_transport_guards_payloads_and_errors(tmp_path,monkeypatch):
    import backend.context.service as module
    from backend.policy.service import NoRedirect
    payload=b'\xef\xbb\xbf[]';failure=None;calls=[]
    class Response(io.BytesIO):
        def read(self,size):
            assert size==10_000_001
            return super().read(size)
    def open_request(sent,timeout):
        calls.append(sent)
        assert timeout==7
        if failure is not None:raise failure
        return Response(payload)
    def opener(handler):
        assert isinstance(handler,NoRedirect)
        return SimpleNamespace(open=open_request)
    monkeypatch.setattr(module,'build_opener',opener)
    service=ContextService(settings(tmp_path,policy_timeout_seconds=7))
    for endpoint in ('statisticsSearch.do','https://example.invalid/steal'):
        with pytest.raises(ValueError,match='unsupported KOSIS endpoint'):service.request(endpoint,{})
    for key in (None,' ',''):
        missing=ContextService(settings(tmp_path,kosis_api_key=key,policy_timeout_seconds=7))
        with pytest.raises(ValueError,match='missing_credentials'):
            missing.request('Param/statisticsParameterData.do',{})
    assert calls==[]
    assert service.request('Param/statisticsParameterData.do',{'tblId':TABLE,'apiKey':'override','format':'xml','jsonVD':'N'})==[]
    sent=urlsplit(calls[-1].full_url);query=parse_qs(sent.query)
    assert (sent.scheme,sent.netloc,sent.path)==('https','kosis.kr','/openapi/Param/statisticsParameterData.do')
    assert query=={'tblId':[TABLE],'apiKey':['generated-secret'],'format':['json'],
                  'method':['getList'],'jsonVD':['Y'],'content':['json']}
    for payload,reason in (
        (b'\xff','provider_invalid_json'),(b'{','provider_invalid_json'),
        (b'{"err":"20"}','provider_error_20'),
        (b'{"err":"generated-secret"}','provider_invalid_response'),
        (b'{"err":"12345"}','provider_invalid_response'),
        (b'null','provider_invalid_response'),(b'1','provider_invalid_response'),
        (json.dumps([{}]*20001).encode(),'provider_invalid_response'),
        (b' '*10_000_001,'response_too_large')):
        with pytest.raises(ValueError) as error:service.request('Param/statisticsParameterData.do',{})
        assert str(error.value)==reason and 'generated-secret' not in str(error.value)
    payload=json.dumps([{}]*20000).encode()
    assert len(service.request('Param/statisticsParameterData.do',{}))==20000
    for failure,reason in (
        (HTTPError('https://kosis.kr/?apiKey=generated-secret',401,'generated-secret',{},None),'provider_http_401'),
        (URLError('generated-secret'),'provider_connection_failed'),
        (TimeoutError('generated-secret'),'provider_connection_failed')):
        with pytest.raises(ContextUnavailable) as error:service.request('Param/statisticsParameterData.do',{})
        assert str(error.value)==reason and 'generated-secret' not in str(error.value)
