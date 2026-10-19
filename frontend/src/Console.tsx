import {useEffect, useState} from 'react';
import {GroupDashboard} from './GroupDashboard';
import {api, Run, Trace, statusText} from './api';
type Alert = {id:string; run_id:string; type:string; cursor:number; status:string; created_at:string; sim_ts:string; received_at:string|null; acknowledged_at:string|null};
type Receipt = {run_to_receipt_ms:number|null; browser_received_at:string; server_received_at:string};
type Age = {age_band:string; stage:number|null; blind_flag:boolean; change_flag:boolean};
type Dong = {dong_cd:string; dong_nm:string; stage:number|null; missing_age_count:number; x:number; y:number; crs:string; coordinate_source:string; ages:Age[]};
type Overview = {run:Run; review:null|{approval:{snapshot_version:string;status:string;operator:string|null;reason:string|null}; proposal:Record<string,unknown>}; classification:null|{metadata?:{analysis_version?:string};analysis?:unknown; status?:string; result?:unknown; dongs?:Dong[]}; traces:Trace[]};
const labels:Record<string,string> = {human_handoff:'담당자 인계',screening_requested:'선별 질문 준비',crisis:'위기', approval_requested:'승인 요청', linkage_completed:'연계 완료',created:'미수신',received:'미확인',acknowledged:'확인됨'};
export function Console() {
  const [client] = useState(()=>{let id=sessionStorage.getItem('client-id'); if(!id){id=crypto.randomUUID(); sessionStorage.setItem('client-id',id);}return id;});
  const [alerts,setAlerts]=useState<Alert[]>([]),[receipts,setReceipts]=useState<Record<string,Receipt>>({});
  const [selected,setSelected]=useState(''),[overview,setOverview]=useState<Overview>();
  const [error,setError]=useState(''),[connection,setConnection]=useState('연결 중'),[busy,setBusy]=useState(false);
  const [operator,setOperator]=useState(''),[reason,setReason]=useState(''),[dong,setDong]=useState('');
  useEffect(()=>{
    let active=true, source:EventSource|undefined;
    const received = new Set<string>();
    function merge(rows:Alert[]) {if(active)setAlerts(old=>[...new Map([...old,...rows].map(a=>[a.id,a])).values()].sort((a,b)=>b.cursor-a.cursor).slice(0,200));}
    async function receive(a:Alert) {
      if(received.has(a.id)) return;
      received.add(a.id);
      try {const receipt=await api<Receipt>(`/alerts/${a.id}/receipt`,{client_id:client,browser_received_at:new Date().toISOString(),sim_ts:a.sim_ts});if(active)setReceipts(old=>({...old,[a.id]:receipt}));}
      catch(e){received.delete(a.id);if(active)setError(String(e));}
    }
    const poll=()=>api<Alert[]>('/alerts?recent=true&limit=200').then(rows=>{
      if(!active)return;
      merge(rows); rows.forEach(receive);
      if(source)return;
      source=new EventSource(`/alerts/stream?after=${Math.max(0,...rows.map(a=>a.cursor))}`);
      source.onopen=()=>setConnection('연결됨'); source.onerror=()=>setConnection('연결 끊김 · 자동 재연결 중');
      source.addEventListener('alert',event=>{const a:Alert=JSON.parse((event as MessageEvent).data); merge([a]);receive(a);});
    }).catch(e=>{if(active)setError(String(e));});
    poll();
    const timer=setInterval(poll,3000);
    return()=>{active=false;source?.close();clearInterval(timer);};
  },[client]);
  useEffect(()=>{
    setOverview(undefined);setReason('');setError('');setDong('');
    if(!selected)return;
    let active=true;
    const refresh=()=>api<Overview>(`/runs/${selected}/overview`).then(v=>{if(active)setOverview(v);}).catch(e=>{if(active)setError(String(e));});
    refresh();const timer=setInterval(refresh,2000);
    return()=>{active=false;clearInterval(timer);};
  },[selected]);
  async function acknowledge(a:Alert) {
    setBusy(true);setError('');
    try{const updated=await api<Alert>(`/alerts/${a.id}/acknowledge`,{client_id:client,operator:operator.trim(),sim_ts:a.sim_ts});setAlerts(old=>old.map(x=>x.id===a.id?{...x,...updated}:x));}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  async function decide(status:string) {
    if(!overview?.review)return;
    const runId=selected;
    setBusy(true);setError('');
    try {await api(`/runs/${runId}/decision`,{snapshot_version:overview.review.approval.snapshot_version,status,operator:operator.trim(),reason:reason.trim()||null});}
    catch(e){setError(`결정 실패 · 최신 상태를 확인하세요. ${String(e)}`);}
    finally {setBusy(false);api<Overview>(`/runs/${runId}/overview`).then(next=>setOverview(old=>old?.run.id===runId?next:old)).catch(e=>setError(String(e)));}
  }
  const sorted=[...alerts].sort((a,b)=>(b.type==='crisis'?2:b.type==='human_handoff'?1:0)-(a.type==='crisis'?2:a.type==='human_handoff'?1:0)||b.cursor-a.cursor);
  const dongs=overview?.classification?.metadata?.analysis_version==='v3'?[]:overview?.classification?.dongs || [], chosen=dongs.find(d=>d.dong_cd===dong);
  return <section><details><summary>8집단 동별 상황판</summary><GroupDashboard embedded/></details><p>알림 SSE {connection} · 최근 200건 · 위기 우선</p><label>담당자 이름 <input value={operator} onChange={e=>setOperator(e.target.value)}/></label>
    <p>자동 수신 확인은 사람의 확인·승인과 별개입니다. 지연은 서버 단조 시계의 실행 시작 → 수신 확인 도착이며, 브라우저 시계와의 차이로 계산하지 않습니다.</p>
    {error && <p role="alert">{error}</p>}
    {!alerts.length && <p>알림이 없습니다. 관찰 페이지에서 시나리오를 실행하세요.</p>}
    <div className="alert-list">{sorted.map(a=><article className={`card ${a.type==='crisis'?'crisis':''}`} key={a.id} data-testid={`alert-${a.run_id}-${a.type}`}><strong>{labels[a.type]} · {labels[a.status]}</strong><p>{a.run_id}</p><p>생성 {a.created_at} · 수신 {a.received_at||'—'} · 사람 확인 {a.acknowledged_at||'—'}</p><p>이 브라우저 수신 지연: {receipts[a.id]?.run_to_receipt_ms == null ? 'N/A (미수신 또는 서버 재시작)' : `${receipts[a.id].run_to_receipt_ms!.toFixed(1)}ms`}</p><div className="toolbar"><button disabled={busy} onClick={()=>setSelected(a.run_id)}>실행 상세</button><button disabled={busy||!operator.trim()||!receipts[a.id]||a.status==='acknowledged'} onClick={()=>acknowledge(a)}>사람 확인</button></div></article>)}</div>
    {overview && <article className="card" data-testid="review-panel"><h2>실행 상세 · {statusText[overview.run.status]}</h2><p>{overview.run.id} · 데이터 {overview.run.data_mode} · LLM {overview.run.llm_mode} · {overview.run.model_version}</p><a href={`/observatory?run=${overview.run.id}`}>전체 타임라인 보기</a>{overview.run.data_mode==='local'&&<p>로컬 사례·상세·캡처는 공개 제외입니다.</p>}
      <h3>분류와 원인</h3><pre>{JSON.stringify({status:overview.classification?.status,assessment:overview.classification?.result,analysis:overview.classification?.analysis},null,2)}</pre>
      {overview.review ? <><h3>배분안·추천 근거·문서 초안</h3>{Boolean(overview.review.proposal.policy_research) && <p>정책 조사 결과는 후보입니다. 개인 자격과 남은 정원은 미확인이며 기존 자원 추천·배정에 포함되지 않습니다.</p>}<p>승인 상태: {overview.review.approval.status} · 담당자 {overview.review.approval.operator||'—'} · 사유 {overview.review.approval.reason||'—'}</p><details open><summary>승인할 내용</summary><pre>{JSON.stringify(overview.review.proposal,null,2)}</pre></details><label>반려 사유 <textarea value={reason} onChange={e=>setReason(e.target.value)}/></label><div className="toolbar"><button disabled={busy||!operator.trim()||overview.review.approval.status!=='pending'} onClick={()=>decide('approved')}>승인</button><button disabled={busy||!operator.trim()||!reason.trim()||overview.review.approval.status!=='pending'} onClick={()=>decide('rejected')}>반려</button></div></>:<p>일반 승인 대상이 없습니다.</p>}
      {!!dongs.length && <><h3>동별 상황판 · {dongs.length}개 동</h3><p>임시 분위 단계 · 동 단계는 연령별 최댓값 · 좌표를 지도 위치로 변환하지 않은 표입니다.</p><label>동 선택 <select value={dong} onChange={e=>setDong(e.target.value)}><option value="">선택</option>{dongs.map(d=><option key={d.dong_cd} value={d.dong_cd}>{d.dong_nm} ({d.dong_cd})</option>)}</select></label><table><thead><tr><th>동</th><th>단계</th><th>결측 연령 수</th><th>좌표·출처</th></tr></thead><tbody>{dongs.map(d=><tr key={d.dong_cd}><td>{d.dong_nm}</td><td>{d.stage??'미평가'}</td><td>{d.missing_age_count}</td><td>{d.x}, {d.y} · {d.crs} · {d.coordinate_source}</td></tr>)}</tbody></table>{chosen&&<table aria-label="연령 상세"><thead><tr><th>연령</th><th>단계</th><th>사각</th><th>변화</th></tr></thead><tbody>{chosen.ages.map(a=><tr key={a.age_band}><td>{a.age_band}</td><td>{a.stage??'미평가'}</td><td>{String(a.blind_flag)}</td><td>{String(a.change_flag)}</td></tr>)}</tbody></table>}</>}
      <details><summary>수신·확인·승인 시간 근거</summary><pre>{JSON.stringify(overview.traces.filter(t=>['alert','received','acknowledged','approval','run_end'].includes(t.kind)),null,2)}</pre></details>
    </article>}
  </section>;
}
