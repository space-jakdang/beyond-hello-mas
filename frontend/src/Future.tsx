import {useEffect,useRef,useState} from 'react';
import {api,statusText} from './api';
import {WorkflowResults,Overview} from './Workflow';
import {AgentMessages} from './MasFlow';

type Batch={id:string;sgg:string;data_mode:string;llm_mode:string;months:string[];assumptions:string[];seed:number;generator_version:string;baseline_input_hash:string;input_hash:string;as_of:string;periods:{ym:string;run_id:string;status:string}[]};
const regions:Record<string,string>={'11230':'강남구','32010':'춘천시'};
export function Future(){
 const query=new URLSearchParams(location.search);
 const [id,setId]=useState(query.get('batch')||''),[region,setRegion]=useState(query.get('region')==='32010'?'32010':'11230');
 const [batch,setBatch]=useState<Batch>(),[selected,setSelected]=useState(query.get('period')||''),[overview,setOverview]=useState<Overview>();
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[resultError,setResultError]=useState('');
 const requestId=useRef(query.get('batch')||'');
 useEffect(()=>{if(!id)return;let active=true;let timer:ReturnType<typeof setInterval>;const refresh=()=>api<Batch>(`/future/batches/${encodeURIComponent(id)}`).then(b=>{if(active){setBatch(b);setError('');if(b.periods.every(p=>['completed','failed','rejected'].includes(p.status)))clearInterval(timer);setSelected(s=>b.periods.some(p=>p.run_id===s)?s:b.periods[0]?.run_id||'');}}).catch(e=>{if(active)setError(String(e));});void refresh();timer=setInterval(refresh,2000);return()=>{active=false;clearInterval(timer);};},[id]);
 useEffect(()=>{setOverview(undefined);setResultError('');if(!selected)return;let active=true;let timer:ReturnType<typeof setInterval>;const refresh=()=>api<Overview>(`/runs/${encodeURIComponent(selected)}/overview`).then(r=>{if(active){setOverview(r);setResultError('');if(['completed','failed','rejected'].includes(r.run.status))clearInterval(timer);}}).catch(e=>{if(active)setResultError(String(e));});void refresh();timer=setInterval(refresh,2000);return()=>{active=false;clearInterval(timer);};},[selected]);
 const running=batch?.periods.some(p=>['pending','running'].includes(p.status));
 async function start(){
  if(busy||running)return;setBusy(true);setError('');
  const next=batch?crypto.randomUUID():requestId.current||crypto.randomUUID();requestId.current=next;
  const url=new URL(location.href);url.searchParams.set('batch',next);url.searchParams.set('region',region);url.searchParams.delete('period');history.replaceState(null,'',url);
  setBatch(undefined);setSelected('');setId('');
  try{const b=await api<Batch>('/future/batches',{request_id:next,sgg:region});setBatch(b);setError('');setSelected(b.periods[0]?.run_id||'');}catch(e){setError(String(e));}finally{setId(next);setBusy(false);}
 }
 const current=overview?.run.id===selected?overview:undefined;
 const proposal=current?.review?.proposal;
 return <section className="workflow-page future-page"><div className="workspace-intro"><div><p className="eyebrow">FUTURE SCENARIO LAB</p><h2>지역을 고르면, 다음 세 기간을 자동으로 분석합니다</h2><p>Supervisor가 분석·통계 검토·자원 조사를 순차 실행합니다. 완료된 기간의 동을 선택하면 해당 근거에 연결된 자원 제안을 볼 수 있습니다.</p></div></div>
 <p className="mode-banner"><strong>합성 미래 시나리오</strong> · 실제 관측과 분리된 가정 실험입니다. 예측 정확도나 미래 자원 가용성을 보장하지 않습니다. <a href="/neighborhoods">실제 기준 자료 확인 →</a></p>
 <form className="task-form" onSubmit={e=>{e.preventDefault();void start();}}><h3>분석 예약</h3><label>시나리오 지역<select value={region} disabled={busy||!!running||(!!id&&!batch&&!error)} onChange={e=>{setRegion(e.target.value);requestId.current='';}}>{Object.entries(regions).map(([code,name])=><option key={code} value={code}>{name}</option>)}</select></label><p>지역 전체 동 · 청년·남성 요청 집단 · 다음 3개월 · 현재 자료 기반 합성 입력</p><p className="muted">시연을 위해 세 기간을 지금 순서대로 실행합니다. 매월 정시에 실행되는 운영 예약은 아닙니다.</p><button className="primary-button" disabled={busy||!!running||(!!id&&!batch&&!error)}>{busy?'분석 등록 중…':running?'예약된 기간을 분석하고 있습니다':error&&!batch?'같은 요청 다시 확인':'미래 시나리오 분석 시작'}</button></form>
 {error&&<p role="alert">분석 정보를 확인하지 못했습니다. 서버 연결·기준 자료를 확인한 후 다시 시도하세요. {error}</p>}
 {!batch&&!busy&&!error&&<ol className="future-guide"><li><strong>1. 지역 선택</strong><p>별도 파일을 입력할 필요가 없습니다.</p></li><li><strong>2. 자동 분석</strong><p>기간마다 분석·검토·정책 도구 기록이 남습니다.</p></li><li><strong>3. 동 선택</strong><p>지도와 자원 카드가 함께 바뀝니다.</p></li></ol>}
 {batch&&<><section className="card"><h3>{regions[batch.sgg]} · 예약된 분석</h3><p>{batch.data_mode==='local'?'실제 지역 자료 기반':'합성 테스트 자료 기반'} · LLM {batch.llm_mode} · 자원 기준 {batch.as_of}</p><div className="future-periods" aria-label="기간별 분석 상태">{batch.periods.map(p=><button key={p.run_id} aria-pressed={selected===p.run_id} onClick={()=>{setSelected(p.run_id);const url=new URL(location.href);url.searchParams.set('period',p.run_id);history.replaceState(null,'',url);}}><strong>{p.ym}</strong><span>{p.status==='pending'?'실행 대기':statusText[p.status]||p.status}</span></button>)}</div><p role="status">{batch.periods.filter(p=>!['pending','running'].includes(p.status)).length} / 3 기간 실행 종료 · 승인은 별도 검토</p><details><summary>생성 가정과 재현 근거</summary><ul>{batch.assumptions.map(a=><li key={a}>{a}</li>)}</ul><p>생성기 {batch.generator_version} · seed {batch.seed}</p><p className="evidence-hash">기준 자료 {batch.baseline_input_hash}<br/>합성 입력 {batch.input_hash}</p></details></section>
 {resultError&&<p role="alert">선택한 기간의 결과를 가져오지 못했습니다. {resultError}</p>}
 {current&&<><h3>{batch.periods.find(p=>p.run_id===selected)?.ym} · 분석 결과</h3>{current.run.error&&<div role="alert"><p>이 기간의 분석에 실패했습니다.</p><details className="workflow-error"><summary>오류 내용</summary><pre>{current.run.error}</pre></details></div>}{proposal?.workflow_version?<><WorkflowResults key={selected} proposal={proposal} runId={selected} dataMode={current.run.data_mode} autoResources/><div className="workflow-actions"><a href={`/console?run=${encodeURIComponent(selected)}`}>담당자가 이 제안 검토하기 →</a><a href={`/workspace?run=${encodeURIComponent(selected)}`}>전체 업무 근거 보기 →</a></div></>:<p role="status">{current.run.status==='failed'?'진행 기록에서 실패 단계를 확인하세요.':current.run.status==='pending'?'이전 기간 분석이 끝나면 시작합니다.':'지역 분석과 자료 검토를 준비하고 있습니다.'}</p>}<details className="card"><summary>에이전트 협업 기록 · {current.traces.filter(t=>t.kind==='agent_message').length}건</summary><AgentMessages traces={current.traces}/></details></>}
 </>}
 </section>;
}
