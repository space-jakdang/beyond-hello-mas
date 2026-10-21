"""Government policy inventory. Coverage describes this API, never all policies in reality."""
from contextlib import closing
from datetime import datetime,timezone
import json
import sqlite3
import time
from typing import Literal
from urllib.parse import urlencode,unquote,urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from pydantic import BaseModel,ConfigDict,Field

Scope=Literal['central','seoul','gangnam','gangwon','chuncheon']
SCOPES=['central','seoul','gangnam','gangwon','chuncheon']
BASE='https://api.odcloud.kr/api/gov24/v3/'
LIMITATION='정부24 API 등록 정보 범위입니다. 미등록 공고·실제 접수 가능 여부·잔여 정원·개인 자격은 보장하지 않습니다.'


def now():return datetime.now(timezone.utc).isoformat()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('provider_redirect_rejected')


class Search(BaseModel):
    model_config=ConfigDict(extra='forbid')
    scopes:list[Scope]=Field(default_factory=lambda:SCOPES.copy(),min_length=1,max_length=5)
    query:str=Field(default='',max_length=200)
    page:int=Field(default=1,ge=1,le=10000)
    per_page:int=Field(default=20,ge=1,le=100)


def jurisdiction(row):
    agency=' '.join(str(row.get('소관기관명') or '').split())
    if agency in ('서울특별시','서울시'):return 'seoul'
    if agency in ('서울특별시 강남구','서울시 강남구'):return 'gangnam'
    if agency in ('강원도','강원특별자치도'):return 'gangwon'
    if agency in ('강원도 춘천시','강원특별자치도 춘천시'):return 'chuncheon'
    if row.get('소관기관유형') in ('중앙행정기관','중앙부처'):return 'central'
    return None


def policy(row,scope):
    def value(key):return str(row.get(key) or '').strip()
    if not value('서비스ID') or not value('서비스명'):raise ValueError('missing policy identity')
    url=value('상세조회URL');parts=urlsplit(url)
    if parts.scheme not in ('https','http') or not parts.hostname or parts.username is not None:url=None
    return {'id':value('서비스ID'),'title':value('서비스명'),'scope':scope,'agency':value('소관기관명'),
            'summary':value('서비스목적요약') or value('서비스목적'),'support':value('지원내용'),
            'eligibility':value('지원대상'),'criteria':value('선정기준'),'application':value('신청방법'),
            'deadline':value('신청기한'),'contact':value('전화문의') or value('문의처'),
            'url':url,'source_updated_at':value('수정일시') or None,
            'eligibility_verified':False,'remaining_capacity':None}


class PolicyService:
    def __init__(self,settings,fetch=None):
        self.settings=settings;self.path=settings.runtime_dir/'policies.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.fetch=fetch or self.request
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS policy_state (name TEXT PRIMARY KEY, body TEXT NOT NULL)');db.commit()

    def read(self,name):
        with closing(sqlite3.connect(self.path)) as db:
            row=db.execute('SELECT body FROM policy_state WHERE name=?',(name,)).fetchone()
        return json.loads(row[0]) if row else None

    def write(self,**values):
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                for name,body in values.items():db.execute('INSERT OR REPLACE INTO policy_state VALUES (?,?)',(name,json.dumps(body,ensure_ascii=False)))

    def request(self,endpoint,params):
        if not self.settings.gov24_service_key:raise ValueError('missing_credentials')
        params={**params,'returnType':'JSON'}
        # Fixed endpoints only; no provider-supplied URL or exception text is executed/returned.
        if endpoint not in ('serviceList','serviceDetail','supportConditions'):raise ValueError('invalid_endpoint')
        request=Request(BASE+endpoint+'?'+urlencode(params),headers={'Authorization':'Infuser '+unquote(self.settings.gov24_service_key.get_secret_value())})
        with build_opener(NoRedirect()).open(request,timeout=self.settings.policy_timeout_seconds) as response:
            raw=response.read(10_000_001)
        if len(raw)>10_000_000:raise ValueError('response_too_large')
        body=json.loads(raw)
        if not isinstance(body,dict) or not isinstance(body.get('data'),list):raise ValueError('invalid_provider_response')
        return body

    def coverage(self):
        snapshot=self.read('snapshot');attempt=self.read('attempt')
        return {'source':'gov24-v3','data_mode':self.settings.data_mode,'credentials_configured':bool(self.settings.gov24_service_key),
                'status':'cached' if snapshot else 'unavailable','fetched_at':snapshot['fetched_at'] if snapshot else None,
                'stale':not snapshot or (datetime.now(timezone.utc)-datetime.fromisoformat(snapshot['fetched_at'])).total_seconds()>3600,
                'source_complete':bool(snapshot and snapshot['source_complete']), 'all_policies_known':False,
                'scopes':{scope:sum(p['scope']==scope for p in snapshot['policies']) if snapshot else None for scope in SCOPES},
                'source_count':snapshot['source_count'] if snapshot else None,'excluded_other_agencies':snapshot['excluded_other_agencies'] if snapshot else None,
                'last_attempt':attempt,'limitation':LIMITATION}

    def refresh(self):
        started=now();deadline=time.monotonic()+60;seen=set();policies=[];total=None;pages=0;excluded=0
        try:
            for page in range(1,self.settings.policy_max_pages+1):
                if time.monotonic()>deadline:raise TimeoutError('refresh_deadline')
                body=self.fetch('serviceList',{'page':page,'perPage':500})
                if type(body.get('totalCount')) is not int or body['totalCount']<0:raise ValueError('invalid_total')
                if total is not None and total!=body['totalCount']:raise ValueError('inventory_changed')
                total=body['totalCount'];rows=body['data']
                if len(rows)>500 or type(body.get('currentCount')) is not int or body['currentCount']!=len(rows):raise ValueError('invalid_page')
                for row in rows:
                    id=row.get('서비스ID')
                    if not isinstance(id,str) or not id or id in seen:raise ValueError('missing_or_duplicate_id')
                    seen.add(id);scope=jurisdiction(row)
                    if scope:policies.append(policy(row,scope))
                    else:excluded+=1
                pages+=1
                if len(seen)==total:break
                if len(seen)>total or not rows:raise ValueError('inconsistent_inventory')
            else:raise ValueError('page_limit')
            snapshot={'started_at':started,'fetched_at':now(),'source_complete':True,'source_count':total,'excluded_other_agencies':excluded,'policies':sorted(policies,key=lambda p:p['id'])}
            self.write(snapshot=snapshot,attempt={'status':'success','at':now(),'pages':pages,'received':len(seen)})
        except Exception as exc:
            reason='missing_credentials' if not self.settings.gov24_service_key and self.fetch==self.request else type(exc).__name__
            self.write(attempt={'status':'failed','at':now(),'reason':reason,'pages':pages,'received':len(seen),'previous_snapshot_preserved':self.read('snapshot') is not None})
        return self.coverage()

    def search(self,search):
        search=Search.model_validate(search);snapshot=self.read('snapshot')
        rows=[p for p in (snapshot['policies'] if snapshot else []) if p['scope'] in search.scopes and search.query.casefold() in ' '.join([p['title'],p['summary'],p['support'],p['eligibility'],p['agency'],p['criteria']]).casefold()]
        start=(search.page-1)*search.per_page
        return {'items':rows[start:start+search.per_page],'total':len(rows),'page':search.page,
                'next_page':search.page+1 if start+search.per_page<len(rows) else None,'coverage':self.coverage()}

    def detail(self,id):
        snapshot=self.read('snapshot')
        cached=next((p for p in (snapshot['policies'] if snapshot else []) if p['id']==id),None)
        if not cached:return {'status':'not_found','policy':None,'conditions':None,'limitation':LIMITATION}
        try:
            detail=self.fetch('serviceDetail',{'page':1,'perPage':10,'cond[서비스ID::EQ]':id})
            records=detail['data']
            if len(records)!=1 or records[0].get('서비스ID')!=id:raise ValueError('detail_filter_mismatch')
            # The detail schema lacks agency type; keep scope from the inventory and reject agency changes.
            if records[0].get('소관기관명')!=cached['agency']:raise ValueError('agency_changed_refresh_required')
            current=policy(records[0],cached['scope']);current['url']=current['url'] or cached['url']
            conditions=self.fetch('supportConditions',{'page':1,'perPage':10,'cond[서비스ID::EQ]':id})
            if len(conditions['data'])>1 or any(r.get('서비스ID')!=id for r in conditions['data']):raise ValueError('conditions_filter_mismatch')
            return {'status':'live','policy':current,'conditions':conditions['data'][0] if conditions['data'] else None,'checked_at':now(),'limitation':LIMITATION}
        except Exception as exc:
            return {'status':'cached','policy':cached,'conditions':None,'checked_at':None,'cached_at':snapshot['fetched_at'],'error':type(exc).__name__,'limitation':LIMITATION}

    def details(self,policy_ids):
        if not 1<=len(policy_ids)<=5 or len(set(policy_ids))!=len(policy_ids):
            raise ValueError('invalid_detail_batch')
        results=[self.detail(id) for id in policy_ids]
        return {'status':'live' if all(r['status']=='live' for r in results) else 'partial',
                'items':results,'requested_ids':policy_ids,'limitation':LIMITATION}
