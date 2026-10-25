"""Bounded KOSIS census context; provider failures never become synthetic local data."""
from contextlib import closing
from datetime import date, datetime, timezone
import json
from math import isfinite
import sqlite3
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from backend.context.contracts import ContextRequest, METRICS, fact_dict, resolve_region
from backend.policy.service import NoRedirect
from backend.tools.indicators import digest
from backend.tools.neighborhoods import boundaries

BASE='https://kosis.kr/openapi/'
TABLE='DT_1IN1502'
UNITS={'persons':'명','households':'가구','houses':'호'}


def now():return datetime.now(timezone.utc).isoformat()


def parse_value(value):
    if value in (None,'','-','...','…','X','x'):return None
    if isinstance(value,bool):raise ValueError('invalid numeric value')
    number=float(str(value).replace(',',''))
    if not isfinite(number) or number<0:raise ValueError('invalid numeric value')
    return number


class ContextUnavailable(ValueError):
    pass


class ContextService:
    def __init__(self,settings,fetch=None):
        self.settings=settings
        self.fetch=fetch or self.request
        self.path=settings.runtime_dir/'regional-context.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS context_cache (key TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS context_history (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
            db.commit()

    def request(self,endpoint,params):
        if endpoint!='Param/statisticsParameterData.do':
            raise ValueError('unsupported KOSIS endpoint')
        if not (self.settings.kosis_api_key and self.settings.kosis_api_key.get_secret_value().strip()):
            raise ValueError('missing_credentials')
        params={**params,'apiKey':self.settings.kosis_api_key.get_secret_value(),'format':'json','method':'getList','jsonVD':'Y','content':'json'}
        request=Request(BASE+endpoint+'?'+urlencode(params))
        try:
            with build_opener(NoRedirect()).open(request,timeout=self.settings.policy_timeout_seconds) as response:
                raw=response.read(10_000_001)
        except HTTPError as exc:raise ContextUnavailable('provider_http_'+str(exc.code)) from None
        except (URLError,TimeoutError):raise ContextUnavailable('provider_connection_failed') from None
        if len(raw)>10_000_000:raise ValueError('response_too_large')
        try:body=json.loads(raw.decode('utf-8-sig'))
        except (UnicodeError,ValueError):raise ContextUnavailable('provider_invalid_json') from None
        if isinstance(body,dict):
            code=str(body.get('err',''))
            raise ContextUnavailable('provider_error_'+code if code.isdecimal() and len(code)<=4 else 'provider_invalid_response')
        if not isinstance(body,list) or len(body)>20000:raise ContextUnavailable('provider_invalid_response')
        return body

    def inventory(self,request,table,params):
        geo,meta=boundaries()
        names={f['properties']['dong_cd']:f['properties']['dong_nm'] for f in geo['features'] if f['properties']['sgg']==request.sgg}
        codes=list(names)
        arguments={'orgId':'101','tblId':table,'objL1':'+'.join(codes),'prdSe':'Y',
                   'startPrdDe':str(request.reference_year),'endPrdDe':str(request.reference_year),'smblChk':'Y',**params}
        cache_id=digest({'source':'kosis-census-3','arguments':arguments,'boundary':meta['subset_sha256']})
        with closing(sqlite3.connect(self.path)) as db:
            saved=db.execute('SELECT body FROM context_cache WHERE key=?',(cache_id,)).fetchone()
        cached=None
        try:
            if saved:
                snapshot=json.loads(saved[0])
                if snapshot['cache_key']!=cache_id or snapshot['source_hash']!=digest(snapshot['rows']):
                    raise ContextUnavailable('cached_source_checksum_or_scope_mismatch')
                elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(snapshot['fetched_at'])).total_seconds()
                if 0<=elapsed<86400:cached=snapshot
            rows=cached['rows'] if cached else self.fetch('Param/statisticsParameterData.do',arguments)
            if not isinstance(rows,list) or not rows or len(rows)>20000:raise ContextUnavailable('provider_no_valid_rows')
            seen=set()
            for row in rows:
                if not isinstance(row,dict) or row.get('TBL_ID')!=table or row.get('ORG_ID')!='101' or row.get('PRD_SE') not in ('A','Y') or row.get('PRD_DE')!=str(request.reference_year) or row.get('ITM_ID') not in params['itmId'].split('+'):raise ContextUnavailable('provider_scope_mismatch')
                if row.get('C1') not in names or row.get('C1_NM')!=names[row['C1']]:raise ContextUnavailable('provider_geography_mismatch')
                categories=params.get('objL2','').split('+')
                category=row.get('C2') if row.get('C2') is not None else ''
                if category not in categories or any(row.get('C'+str(i)) not in (None,'') for i in range(3,9)):
                    raise ContextUnavailable('provider_scope_mismatch')
                expected_unit={'T100':'명','T200':'가구','T310':'호'}.get(row['ITM_ID']) if table==TABLE else '가구' if table=='DT_1JC1502' else '명'
                if row.get('UNIT_NM')!=expected_unit:raise ContextUnavailable('provider_unit_mismatch')
                identity=(row.get('C1'),row['ITM_ID'],row.get('C2'))
                if identity in seen:raise ContextUnavailable('provider_duplicate_observation')
                seen.add(identity)
                value=parse_value(row.get('DT'))
                if value is not None and not value.is_integer():raise ContextUnavailable('provider_invalid_count')
        except Exception:
            if saved:
                with closing(sqlite3.connect(self.path)) as db:
                    db.execute('DELETE FROM context_cache WHERE key=?',(cache_id,));db.commit()
            raise
        if cached:return cached
        snapshot={'rows':rows,'fetched_at':now(),'source_hash':digest(rows),'cache_key':cache_id}
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('INSERT OR REPLACE INTO context_cache VALUES (?,?)',(cache_id,json.dumps(snapshot,ensure_ascii=False)));db.commit()
        return snapshot

    def profile(self,request):
        request=ContextRequest.model_validate(request)
        if self.settings.data_mode=='sample':return self.synthetic(request)
        geo,_=boundaries()
        if not any(f['properties']['dong_cd']==request.dong_cd and f['properties']['sgg']==request.sgg for f in geo['features']):
            raise ValueError('unknown administrative neighborhood')
        result={'version':'regional-context-1','source':'kosis','data_mode':'local','request':request.model_dump(mode='json'),
                'status':'unavailable','reason':'missing_credentials','facts':[],
                'limitations':['집계 문맥이며 개인 자격·고립 인원·서비스 수요가 아닙니다.','과거 당시의 자료 가용성과 경계 동일성은 미검증입니다.']}
        if not (self.settings.kosis_api_key and self.settings.kosis_api_key.get_secret_value().strip()):return self.finish(result)
        snapshots={};failures={}
        for table,params in ((TABLE,{'itmId':'T100+T200+T310'}),('DT_1JC1502',{'itmId':'T0+T1'}),
                             ('DT_1IN1503',{'itmId':'T00','objL2':'000+020005+025+030+035+104'})):
            try:snapshots[table]=self.inventory(request,table,params)
            except Exception as exc:failures[table]=str(exc) if isinstance(exc,ContextUnavailable) else 'provider_inputs_missing_or_invalid'
        try:
            if not snapshots:raise ContextUnavailable(failures.get(TABLE,'provider_inputs_missing_or_invalid'))
            snapshot=snapshots.get(TABLE) or next(iter(snapshots.values()))
            rows=[row for data in snapshots.values() for row in data['rows']];areas={}
            for row in rows:
                if row['C1'] in areas and areas[row['C1']]['addr_name']!=row['C1_NM']:raise ValueError('conflicting geography names')
                areas[row['C1']]={'cd':row['C1'],'addr_name':row['C1_NM']}
            identity=resolve_region(request,list(areas.values()))
            definitions={
                'total_population':(TABLE,'T100',[], 'census_residents'),
                'total_households':(TABLE,'T200',[], 'census_all_households'),
                'total_housing':(TABLE,'T310',[], 'census_housing'),
                'general_households':('DT_1JC1502','T0',[], 'census_general_households'),
                'one_person_households':('DT_1JC1502','T1',[], 'census_general_households'),
                'senior_population':('DT_1IN1503','T00',['104'], 'census_residents_age_table'),
                'youth_population':('DT_1IN1503','T00',['020005','025','030','035'], 'census_residents_age_table')}
            age_snapshot=snapshots.get('DT_1IN1503')
            total_age=[r for r in age_snapshot['rows'] if r.get('C1')==identity.provider_code and r.get('C2')=='000'] if age_snapshot else []
            total_base=[r for r in snapshots.get(TABLE,{}).get('rows',[]) if r.get('C1')==identity.provider_code and r.get('ITM_ID')=='T100']
            same_total=(len(total_age)==len(total_base)==1 and parse_value(total_base[0]['DT']) is not None
                        and parse_value(total_age[0]['DT'])==parse_value(total_base[0]['DT']))
            facts=[]
            for metric,(_,unit) in METRICS.items():
                table,item,categories,population=definitions.get(metric,(None,'',[],'not_configured'))
                data=snapshots.get(table);matches=[r for r in data['rows'] if r.get('C1')==identity.provider_code and r.get('C1_NM')==identity.dong_nm and r.get('ITM_ID')==item and (not categories or r.get('C2') in categories)] if data and item else []
                expected=len(categories) if categories else 1
                if len(matches)>expected or categories and len({r.get('C2') for r in matches})!=len(matches):raise ValueError('ambiguous_metric')
                if any(r.get('UNIT_NM')!=UNITS[unit] for r in matches):raise ValueError('provider_unit_mismatch')
                values=[parse_value(r.get('DT')) for r in matches]
                value=sum(values) if len(values)==expected and all(v is not None for v in values) else None
                if metric in ('senior_population','youth_population') and same_total:population='census_residents'
                source_hash=data['source_hash'] if data else digest({'table':table,'metric':metric,'status':failures.get(table,'not_configured'),'year':request.reference_year})
                facts.append(fact_dict({'metric':metric,'value':value,'unit':unit,'geography_level':'dong',
                    'geography_code':identity.provider_code,'geography_version':str(request.reference_year)+':'+identity.boundary_version+':parent_name_only',
                    'reference_year':request.reference_year,'population':population,
                    'age_definition':'19-34' if metric=='youth_population' else '65+' if metric=='senior_population' else 'all_ages',
                    'source':'kosis','source_table':table,'source_items':[item] if item else [],'source_dimensions':categories,
                    'source_url':'https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId='+table if table else 'https://kosis.kr/openapi/','source_hash':source_hash if table else digest({'metric':metric,'status':'not_configured'}),
                    'fetched_at':data['fetched_at'] if data else snapshot['fetched_at'],
                    'status':'observed' if value is not None else 'missing','reason':None if value is not None else failures.get(table,'metric_unavailable_or_suppressed') if table else 'metric_not_configured'}))
            observed=sum(f['status']=='observed' for f in facts)
            result.update(identity=identity.model_dump(mode='json'),facts=facts,status='ready' if observed==len(METRICS) else 'partial' if observed else 'unavailable',
                          reason=None if observed else 'no_observed_metrics',fetched_at=snapshot['fetched_at'])
        except Exception as exc:
            result['reason']=str(exc) if isinstance(exc,ContextUnavailable) else 'provider_inputs_missing_or_invalid'
        return self.finish(result)

    def synthetic(self,request):
        from backend.tools.segments_v3 import load_segments
        rows,_=load_segments(self.settings)
        local=next((r for r in rows if r.sgg==request.sgg and r.dong_cd==request.dong_cd),None)
        if local is None:raise ValueError('unknown sample neighborhood')
        seed=int(digest(request.dong_cd)[:6],16)
        population=1000+seed%10000;households=population//2
        values={'total_population':population,'total_households':households,'general_households':households,'one_person_households':households*(25+seed%25)//100,
                'senior_population':population*(10+seed%20)//100,'youth_population':population*(15+seed%20)//100,
                'total_housing':households+20,'population_density':500+seed%5000,'average_age':35+seed%20}
        facts=[fact_dict({'metric':m,'value':float(v),'unit':METRICS[m][1],'geography_level':'dong','geography_code':request.dong_cd,
            'geography_version':'synthetic-grid-1','reference_year':request.reference_year,'population':'synthetic_aggregate',
            'age_definition':'19-34' if m=='youth_population' else '65+' if m=='senior_population' else 'all_ages',
            'source':'synthetic_fixture','source_url':'https://example.invalid/regional-fixture','source_hash':digest(values),
            'fetched_at':now(),'status':'observed'}) for m,v in values.items()]
        return self.finish({'version':'regional-context-1','source':'synthetic_fixture','data_mode':'sample','status':'ready','reason':None,
            'request':request.model_dump(mode='json'),'identity':{'sgg':request.sgg,'dong_cd':request.dong_cd,'dong_nm':local.dong_nm},'facts':facts,
            'limitations':['생성한 지역 정보 fixture이며 실제 인구·가구 관측이 아닙니다.']})

    def resources(self,request):
        from backend.tools.catalog import load_catalog
        from backend.policy.service import PolicyService, Search
        scopes=['central','seoul','gangnam'] if request.sgg=='11230' else ['central','gangwon','chuncheon']
        try:
            catalog=[r.model_dump(mode='json') for r in load_catalog(self.settings.catalog_path)
                     if set(r.jurisdiction)&{'KR',request.sgg[:2],request.sgg}]
            resources={'status':'available','items':catalog[:10],'total':len(catalog),'input_hash':digest(catalog)}
        except (OSError,ValueError):resources={'status':'unavailable','items':[],'total':None}
        try:policies=PolicyService(self.settings).search(Search(scopes=scopes,per_page=5))
        except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):
            policies={'items':[],'total':None,'coverage':{'status':'unavailable','reason':'cached_policy_inputs_missing_or_invalid'}}
        return {'catalog':resources,'policies':policies,
                'limitation':'등록된 사업·신청 경로이며 시설 수·정원·이용량이나 개인 자격의 확인이 아닙니다.'}

    def last_attempt(self):
        with closing(sqlite3.connect(self.path)) as db:
            row=db.execute('SELECT body FROM context_history ORDER BY id DESC LIMIT 1').fetchone()
        if row is None:return None
        attempt=json.loads(row[0])
        if not isinstance(attempt,dict) or not attempt:raise ValueError('invalid context history')
        return attempt

    def finish(self,result):
        result['resources']=self.resources(ContextRequest.model_validate(result['request']))
        content={k:v for k,v in result.items() if k!='fetched_at'}
        content['facts']=[{k:v for k,v in f.items() if k!='fetched_at'} for f in result['facts']]
        result['input_hash']=digest(content)
        attempt={k:result[k] for k in ('request','source','data_mode','status','reason','input_hash')}
        attempt.update(at=now(),source_hashes=sorted({f['source_hash'] for f in result['facts']}))
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                db.execute('INSERT INTO context_history (body) VALUES (?)',(json.dumps(attempt,ensure_ascii=False),))
                db.execute('DELETE FROM context_history WHERE id NOT IN (SELECT id FROM context_history ORDER BY id DESC LIMIT 500)')
        return result


def router(settings):
    from fastapi import APIRouter,HTTPException
    result=APIRouter();service=ContextService(settings)
    @result.get('/analysis/regional-context')
    def regional_context(sgg: str,dong_cd: str,reference_year:int|None=None,as_of:date|None=None):
        try:
            as_of=as_of or datetime.now(ZoneInfo('Asia/Seoul')).date()
            year=reference_year if reference_year is not None else min(settings.regional_reference_year,as_of.year)
            request=ContextRequest(sgg=sgg,dong_cd=dong_cd,reference_year=year,as_of=as_of)
        except ValueError:raise HTTPException(422,'지역 정보 요청의 지역·연도·기준일을 확인하세요.')
        try:return service.profile(request)
        except ValueError:raise HTTPException(422,'등록된 동의 지역 정보만 요청할 수 있습니다.')
    return result
