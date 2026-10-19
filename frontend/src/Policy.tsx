import {FormEvent, useEffect, useState} from 'react';
import {api} from './api';
const scopes:Record<string,string> = {central:'중앙정부',seoul:'서울시',gangnam:'강남구',gangwon:'강원도',chuncheon:'춘천시'};
type Coverage = {credentials_configured:boolean; status:string; fetched_at:string|null; stale:boolean; scopes:Record<string,number|null>; source_count:number|null; limitation:string; last_attempt:{status:string;reason?:string}|null};
type PolicyItem = {id:string;title:string;agency:string;scope:string;summary:string;support:string;eligibility:string;criteria:string;deadline:string;application:string;contact:string;url:string};
type SearchResult = {items:PolicyItem[];total:number;page:number;next_page:number|null;coverage:Coverage};
type Detail = {status:string;policy:PolicyItem|null;checked_at?:string;cached_at?:string;limitation:string};
const date = (value:string|null|undefined) => value ? new Date(value).toLocaleString('ko-KR') : '아직 확인하지 않음';
export function Policy() {
  const [coverage,setCoverage]=useState<Coverage>();
  const [result,setResult]=useState<SearchResult>();
  const [detail,setDetail]=useState<Detail>();
  const [query,setQuery]=useState(''), [scope,setScope]=useState('all');
  const [filter,setFilter]=useState({query:'',scope:'all'});
  const [busy,setBusy]=useState(false), [error,setError]=useState('');
  async function search(page=1, selection=filter) {
    const params=new URLSearchParams({query:selection.query,page:String(page),per_page:'12'});
    for(const key of selection.scope==='all'?Object.keys(scopes):[selection.scope]) params.append('scopes',key);
    const response=await api<SearchResult>(`/policies?${params}`);
    setResult(response);setCoverage(response.coverage);
  }
  useEffect(()=>{setBusy(true);search().catch(e=>setError(String(e))).finally(()=>setBusy(false));},[]);
  async function perform(action:()=>Promise<void>) {
    setBusy(true);setError('');
    try {await action();} catch(e){setError(String(e));} finally {setBusy(false);}
  }
  function submit(event:FormEvent) {
    event.preventDefault();const selection={query,scope};setFilter(selection);setDetail(undefined);
    void perform(()=>search(1,selection));
  }
  return <section>
    <p className="page-intro">지원 정책의 출처와 최신성을 확인하고, 필요한 조사를 에이전트에게 맡기세요. 정책 자료와 LLM 실행 모드는 서로 독립적입니다.</p>
    <section className="card" aria-labelledby="policy-source"><div className="section-heading"><div><p className="eyebrow">SOURCE · GOVERNMENT 24</p><h2 id="policy-source">정부24 연결 및 수집 상태</h2></div><button disabled={busy || !coverage?.credentials_configured} onClick={()=>void perform(async()=>{const current=await api<Coverage>('/policies/refresh',{});setCoverage(current);await search();})}>{busy?'조회 중…':'정부24 목록 갱신'}</button></div>
      {coverage ? <><div className="source-stats"><div><span>서버 인증키</span><strong>{coverage.credentials_configured?'설정됨':'미설정'}</strong></div><div><span>최근 목록 수집</span><strong>{date(coverage.fetched_at)}</strong></div><div><span>자료 상태</span><strong>{coverage.status==='cached'?(coverage.stale?'저장된 목록 · 갱신 필요':'저장된 목록'):'수집 전'}</strong></div></div>
        <p>정부24 등록 목록 {coverage.source_count?.toLocaleString() ?? '—'}건 중 아래 관할을 조회합니다. 목록은 저장본이며, 정책 상세를 열면 최신 조건을 다시 요청합니다.</p>
        <div className="scope-counts">{Object.entries(scopes).map(([key,name])=><span key={key}>{name} <strong>{coverage.scopes[key]?.toLocaleString() ?? '—'}</strong></span>)}</div>
        {coverage.last_attempt?.status==='failed'&&<p role="alert">최근 갱신 실패 ({coverage.last_attempt.reason}). 이전 저장본이 있으면 유지합니다.</p>}
        {!coverage.credentials_configured&&<p>서버의 GOV24_SERVICE_KEY 설정이 필요합니다. 키를 입력한 뒤 개발 서버를 다시 시작하세요.</p>}
        <p className="muted">{coverage.limitation}</p></>:<p>자료 연결 상태를 확인하고 있습니다.</p>}
    </section>
    <form className="toolbar card" onSubmit={submit}><label>관할 <select aria-label="관할" value={scope} onChange={e=>setScope(e.target.value)}><option value="all">전체 5개 관할</option>{Object.entries(scopes).map(([key,name])=><option key={key} value={key}>{name}</option>)}</select></label><label className="search-field">정책 검색 <input value={query} onChange={e=>setQuery(e.target.value)} maxLength={200} placeholder="예: 돌봄, 주거, 상담"/></label><button disabled={busy}>검색</button></form>
    {error&&<p role="alert">{error}</p>}
    <div className="policy-layout"><section aria-label="정책 검색 결과" aria-busy={busy}><h2>검색 결과 <small>{result?.total.toLocaleString() ?? '—'}건</small></h2>
      {result?.items.length===0&&<p className="card">조회된 정책이 없습니다. 수집 상태를 확인하거나 검색어·관할을 변경하세요.</p>}
      {result?.items.map(item=><article className="card" key={item.id}><p className="eyebrow">{scopes[item.scope]} · {item.agency}</p><h3>{item.title}</h3><p>{item.summary||item.support||'상세 정보에서 지원 내용을 확인하세요.'}</p><button disabled={busy} onClick={()=>void perform(async()=>{setDetail(undefined);setDetail(await api<Detail>(`/policies/${encodeURIComponent(item.id)}`));})}>상세 확인 · {item.title}</button></article>)}
      {result&&<div className="toolbar"><button disabled={busy||result.page<=1} onClick={()=>void perform(()=>search(result.page-1))}>이전</button><span>{result.page} 페이지</span><button disabled={busy||!result.next_page} onClick={()=>void perform(()=>search(result.next_page!))}>다음</button></div>}
    </section><aside className="card policy-detail" aria-label="정책 상세" aria-live="polite"><h2>지원 조건 확인</h2>{detail?.policy?<><p className="eyebrow">{detail.status==='live'?'정부24 최신 상세 확인':'저장된 상세 · 실시간 확인 실패'}</p><h3>{detail.policy.title}</h3><p>확인 시각: {date(detail.checked_at||detail.cached_at)}</p><dl>{(['support','eligibility','criteria','deadline','application','contact'] as const).map((key,i)=><div key={key}><dt>{['지원 내용','지원 대상','선정 기준','신청 기한','신청 방법','문의처'][i]}</dt><dd>{detail.policy![key]||'제공된 정보 없음'}</dd></div>)}</dl>{/^https?:\/\//.test(detail.policy.url)&&<a href={detail.policy.url} target="_blank" rel="noreferrer">공식 안내 원문 열기 ↗</a>}<p className="muted">{detail.limitation}</p></>:<p>{detail?'해당 정책을 찾지 못했습니다. 목록을 갱신해 주세요.':'검색 결과에서 정책을 선택하면 지원 대상·선정 기준·신청 방법을 확인할 수 있습니다.'}</p>}</aside></div>
    <section className="card"><h2>에이전트에게 추가 조사 맡기기</h2><p>관찰 화면에서 조사 목표와 관할을 지정하면 Supervisor가 정책 에이전트에 위임합니다. 에이전트는 MCP의 목록 갱신·검색·상세 조회 도구를 사용하고, 조회 근거를 기록합니다.</p><a className="primary-link" href="/observatory#policy-task">정책 조사 지시하기 →</a><p>API 밖의 미등록 공고나 실제 접수 가능 여부는 공식 안내 원문과 기관 문의로 보완해야 합니다. 현재 자동 조사는 정부24 등록 자료 범위입니다.</p></section>
  </section>;
}
