import {useEffect, useState} from 'react';
import {WorkflowResults,Proposal} from './Workflow';
import {GroupDashboard} from './GroupDashboard';
import {api, Run, Trace, statusText} from './api';
type Alert = {id:string; run_id:string; type:string; cursor:number; status:string; created_at:string; sim_ts:string; received_at:string|null; acknowledged_at:string|null};
type Receipt = {run_to_receipt_ms:number|null; browser_received_at:string; server_received_at:string};
type Age = {age_band:string; stage:number|null; blind_flag:boolean; change_flag:boolean};
type Dong = {dong_cd:string; dong_nm:string; stage:number|null; missing_age_count:number; x:number; y:number; crs:string; coordinate_source:string; ages:Age[]};
type Overview = {run:Run; review:null|{approval:{snapshot_version:string;status:string;operator:string|null;reason:string|null}; proposal:Record<string,unknown>}; classification:null|{metadata?:{analysis_version?:string};analysis?:unknown; status?:string; result?:unknown; dongs?:Dong[]}; traces:Trace[]};
const labels:Record<string,string> = {human_handoff:'담당자 확인 요청',screening_requested:'선별 질문 준비',crisis:'위기 신호',approval_requested:'검토·승인 요청',linkage_completed:'후속 절차 기록',created:'브라우저 수신 전',received:'담당자 확인 전',acknowledged:'담당자 확인 완료'};
const approvalLabels:Record<string,string> = {pending:'검토 대기',approved:'승인됨',rejected:'반려됨'};
const scopeLabels:Record<string,string> = {monthly_group_allocation:'지역 자원 검토안',case_referral_plan:'사례 지원 연결안',assessment_followup:'추가 확인 제안'};
const dateTime=(value:string|null|undefined)=>{if(!value)return '아직 기록되지 않음';const date=new Date(value);return Number.isNaN(date.getTime())?'시간을 확인할 수 없음':new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',dateStyle:'medium',timeStyle:'short'}).format(date);};
export function Console() {
  const [filter,setFilter]=useState('all');
  const [client] = useState(()=>{let id=sessionStorage.getItem('client-id'); if(!id){id=crypto.randomUUID(); sessionStorage.setItem('client-id',id);}return id;});
  const [alerts,setAlerts]=useState<Alert[]>([]),[receipts,setReceipts]=useState<Record<string,Receipt>>({});
  const [selected,setSelected]=useState(new URLSearchParams(location.search).get('run')||''),[overview,setOverview]=useState<Overview>();
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
      source.onopen=()=>setConnection('연결됨'); source.onerror=()=>setConnection('연결 끊김 · 자동으로 다시 연결 중');
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
  async function revise() {
    if(!overview?.review)return;
    setBusy(true);setError('');
    try{const child=await api<Run>(`/runs/${selected}/revision`,{snapshot_version:overview.review.approval.snapshot_version,operator:operator.trim(),reason:reason.trim()});location.assign(`/workspace?run=${encodeURIComponent(child.id)}`);}
    catch(e){setError(`보완 요청 실패 · 최신 상태를 확인하세요. ${String(e)}`);setBusy(false);}
  }
  const sorted=[...alerts].sort((a,b)=>(b.type==='crisis'?2:b.type==='human_handoff'?1:0)-(a.type==='crisis'?2:a.type==='human_handoff'?1:0)||b.cursor-a.cursor);
  const matches=(a:Alert,key:string)=>key==='unconfirmed'?a.status!=='acknowledged':key==='urgent'?['crisis','human_handoff'].includes(a.type):key==='approval'?a.type==='approval_requested':true;
  const filters=[['all','전체 알림'],['urgent','위기·인계'],['unconfirmed','사람 미확인'],['approval','승인 요청 알림']];
  const filtered=sorted.filter(a=>matches(a,filter));
  const dongs=overview?.classification?.metadata?.analysis_version==='v3'?[]:overview?.classification?.dongs || [], chosen=dongs.find(d=>d.dong_cd===dong);
  const proposal=overview?.review?.proposal;
  const draft=proposal?.draft as {text?:string}|undefined, explanations=proposal?.explanations as {summary?:string}|undefined;
  const legacySummary=(draft?.text||explanations?.summary)?.replace(/^fake:\s*/,'');
  const assignments=proposal?.assignments as {recommendations?:{name?:string}[]}[]|undefined;
  const legacyCandidates=[...new Set((Array.isArray(assignments)?assignments:[]).flatMap(row=>Array.isArray(row.recommendations)?row.recommendations.flatMap(candidate=>typeof candidate.name==='string'?[candidate.name]:[]):[]))];
  return <section><details><summary>지역·연령별 분석 표 보기</summary><GroupDashboard embedded/></details><p role="status">실시간 알림 {connection} · 최근 최대 200건 · 위기·인계 우선</p><label>담당자 이름 <input value={operator} onChange={e=>setOperator(e.target.value)}/></label>
    <p>알림이 이 브라우저에 도착하면 자동으로 수신 기록을 남깁니다. 이는 담당자의 확인이나 승인과 다릅니다. 수신 지연은 업무 시작부터 브라우저 도착까지 서버가 측정하며 담당자 확인까지 걸린 시간은 포함하지 않습니다.</p>
    {error && <div role="alert"><p>화면 정보를 불러오거나 처리하지 못했습니다. 최신 상태를 다시 확인하세요.</p><details><summary>오류 정보</summary><pre>{error}</pre></details></div>}
    {!alerts.length && <p>새 알림이 없습니다. 관찰 페이지에서 시나리오를 실행하면 여기에 표시됩니다.</p>}
    <section aria-label="알림 우선순위 필터" className="alert-filters"><h2>먼저 확인할 알림</h2><p>최근 알림 최대 200건 중 조건에 맞는 항목을 표시합니다. 승인 요청에는 이미 처리된 항목도 있을 수 있으니 현재 상태는 실행 상세에서 확인하세요.</p><div className="filter-cards">{filters.map(([key,name])=><button key={key} aria-pressed={filter===key} onClick={()=>setFilter(key)}><span>{name}</span><strong>{alerts.filter(a=>matches(a,key)).length}</strong></button>)}</div></section>
    {!!alerts.length&&!filtered.length&&<p role="status">선택한 조건에 맞는 알림이 없습니다.</p>}
    <div className="alert-list">{filtered.map(a=><article className={`card ${a.type==='crisis'?'crisis':''}`} key={a.id} data-alert-type={a.type} data-alert-status={a.status} data-testid={`alert-${a.run_id}-${a.type}`}><strong>{labels[a.type]||'확인할 알림'} · {labels[a.status]||'상태 확인 필요'}</strong><p>알림 생성 {dateTime(a.created_at)} · 브라우저 도착 {dateTime(a.received_at)} · 담당자 확인 {dateTime(a.acknowledged_at)}</p><p>브라우저 수신 지연: {receipts[a.id]?.run_to_receipt_ms == null ? '측정할 수 없음 (수신 기록 없음 또는 서버 재시작)' : receipts[a.id].run_to_receipt_ms!<1000?`${receipts[a.id].run_to_receipt_ms!.toFixed(0)}밀리초`:`${(receipts[a.id].run_to_receipt_ms!/1000).toFixed(1)}초`}</p><details><summary>실행 식별 정보</summary><p>실행 ID {a.run_id}</p></details><div className="toolbar"><button disabled={busy} onClick={()=>setSelected(a.run_id)}>실행 상세</button><button disabled={busy||!operator.trim()||!receipts[a.id]||a.status==='acknowledged'} onClick={()=>acknowledge(a)}>사람 확인</button></div></article>)}</div>
    {overview && overview.run.id===selected && <article className="card" data-testid="review-panel">
      <h2>검토 대상 · {statusText[overview.run.status]||'상태 확인 필요'}</h2><p>업무 시작 {dateTime(overview.run.started_at)} · {overview.run.data_mode==='local'?'로컬 자료':overview.run.data_mode==='sample'?'합성 테스트 자료':'자료 설정 확인 필요'}</p>
      <details><summary>실행 식별 정보와 모델 설정</summary><p>실행 ID {overview.run.id} · 자료 모드 {overview.run.data_mode} · 모델 실행 방식 {overview.run.llm_mode} · 모델 버전 {overview.run.model_version}</p></details><a href={`/observatory?run=${overview.run.id}`}>진행 기록 자세히 보기</a>{overview.run.data_mode==='local'&&<p>로컬 자료를 사용했습니다. 사례와 상세 자료는 공개 화면에 포함하지 않습니다.</p>}
      <details><summary>분류 결과 원문</summary><pre>{JSON.stringify({status:overview.classification?.status,assessment:overview.classification?.result,analysis:overview.classification?.analysis},null,2)}</pre></details>
      {overview.review ? <><h3>{overview.review.proposal.workflow_version?'담당자 검토':`담당자 검토 · ${scopeLabels[String(overview.review.proposal.scope)]||'제안'}`}</h3>{Boolean(overview.review.proposal.workflow_version)&&<WorkflowResults key={selected} proposal={overview.review.proposal as unknown as Proposal} runId={selected} dataMode={overview.run.data_mode} reviewable/>}{!overview.review.proposal.workflow_version&&<><p>{legacySummary||'자동 요약이 없습니다. 세부정보를 확인한 뒤 판단하세요.'}</p>{!!legacyCandidates.length&&<><h4>추천 자원 후보</h4><ul>{legacyCandidates.map(name=><li key={name}>{name}</li>)}</ul></>}<p>이 제안은 자격·접수 가능 여부를 확정하지 않습니다.</p></>}{Boolean(overview.review.proposal.policy_research) && <p>정책 조사 결과는 후보입니다. 개인 자격과 남은 정원은 확인하지 않았으며 기존 자원 추천·배정에 포함되지 않습니다.</p>}
      <p>검토 상태: {approvalLabels[overview.review.approval.status]||'상태 확인 필요'} · 담당자 {overview.review.approval.operator||'기록 없음'} · 판단 사유 {overview.review.approval.reason||'기록 없음'}</p><p>승인은 시스템 내부의 후속 절차를 진행합니다. 외부 기관에 자동 전달하거나 실제 지원을 배정하지 않습니다. 반려·보완 요청에는 사유가 필요합니다.</p><p>보완 요청은 현재 제안을 덮어쓰지 않고 별도 검토 실행을 만듭니다.</p>
      <label>검토 사유 <textarea aria-describedby="review-reason-help" value={reason} onChange={e=>setReason(e.target.value)}/></label><p id="review-reason-help">반려하거나 보완을 요청할 때는 사유를 적어 주세요. 승인할 때는 선택 입력입니다.</p><div className="toolbar"><button disabled={busy||!operator.trim()||overview.review.approval.status!=='pending'} onClick={()=>decide('approved')}>승인</button><button disabled={busy||!operator.trim()||!reason.trim()||overview.review.approval.status!=='pending'} onClick={()=>decide('rejected')}>반려</button>{Boolean(overview.review.proposal.workflow_version)&&<button disabled={busy||!operator.trim()||!reason.trim()||overview.review.approval.status!=='pending'} onClick={()=>void revise()}>보완 요청</button>}</div><details><summary>승인 원문과 기술 자료</summary><pre>{JSON.stringify(overview.review.proposal,null,2)}</pre></details></>:<p>담당자 검토 대상이 없습니다.</p>}
      {!!dongs.length && <><h3>동별 우선 확인 · {dongs.length}개 동</h3><p>동 단계는 해당 동의 연령별 단계 중 가장 높은 값입니다. 개인 판정이 아니며, 자료가 없는 집단은 단계를 계산하지 않습니다.</p><label>동 선택 <select value={dong} onChange={e=>setDong(e.target.value)}><option value="">동 선택</option>{dongs.map(d=><option key={d.dong_cd} value={d.dong_cd}>{d.dong_nm}</option>)}</select></label><table><thead><tr><th>동</th><th>우선 확인 단계</th><th>자료가 없는 연령집단</th><th>위치 원자료</th></tr></thead><tbody>{dongs.map(d=><tr key={d.dong_cd}><td>{d.dong_nm}</td><td>{d.stage===null?'단계 없음':`${d.stage}단계`}</td><td>{d.missing_age_count===0?'없음':`${d.missing_age_count}개`}</td><td><details><summary>위치 세부정보</summary><p>{d.x}, {d.y} · 좌표 체계 {d.crs} · 출처 {d.coordinate_source}</p><p>동 코드 {d.dong_cd}</p></details></td></tr>)}</tbody></table>{chosen&&<table aria-label="연령 상세"><caption>{chosen.dong_nm}의 연령집단별 확인 결과</caption><thead><tr><th>연령집단</th><th>우선 확인 단계</th><th>추가 확인 필요</th><th>변화 기준 해당</th></tr></thead><tbody>{chosen.ages.map(a=><tr key={a.age_band}><td>{a.age_band}</td><td>{a.stage===null?'단계 없음':`${a.stage}단계`}</td><td>{a.blind_flag?'필요':'없음'}</td><td>{a.change_flag?'해당':'해당 없음'}</td></tr>)}</tbody></table>}</>}
      <details><summary>수신·확인·승인 시간 근거</summary><pre>{JSON.stringify(overview.traces.filter(t=>['alert','received','acknowledged','approval','run_end'].includes(t.kind)),null,2)}</pre></details>
    </article>}
  </section>;
}
