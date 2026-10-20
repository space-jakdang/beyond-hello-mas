import {useEffect, useState} from 'react';
import {ReactFlow, Background, Controls} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {api, Run, Trace, scenarios, statusText} from './api';
const roles = ['supervisor', 'classify', 'regional_analyst', 'regional_reviewer', 'statistics', 'match', 'approval', 'link', 'policy'];
const roleNames:Record<string,string>={supervisor:'Supervisor',statistics:'통계 분석',regional_analyst:'지역 분석',regional_reviewer:'근거 검토',match:'자원 매칭'};
export function Observatory() {
  const [goal, setGoal] = useState('고립 위험 주민에게 도움이 될 지원 정책을 조사해 주세요.');
  const [policyScopes, setPolicyScopes] = useState(['central','seoul','gangnam','gangwon','chuncheon']);
  const scopeNames: Record<string,string> = {central:'중앙정부',seoul:'서울시',gangnam:'강남구',gangwon:'강원도',chuncheon:'춘천시'};
  const [runs, setRuns] = useState<Run[]>([]), [run, setRun] = useState<Run>();
  const [id, setId] = useState(new URLSearchParams(location.search).get('run') || '');
  const [scenario, setScenario] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [traces, setTraces] = useState<Trace[]>([]), [detail, setDetail] = useState<Trace>();
  const [connection, setConnection] = useState('대기'), [agent, setAgent] = useState('all');
  const [replay, setReplay] = useState<number | null>(null), [speed, setSpeed] = useState(1);
  useEffect(() => { api<Run[]>('/runs').then(setRuns).catch(e => setError(String(e))); }, []);
  useEffect(() => {
    setTraces([]); setDetail(undefined); setRun(undefined); setReplay(null); setError('');
    if (!id) return;
    history.replaceState(null, '', `${location.pathname}?run=${encodeURIComponent(id)}`);
    let active = true;
    const refresh = () => api<Run>(`/runs/${encodeURIComponent(id)}`).then(r => {if (active) {setRun(r); setRuns(old => [r, ...old.filter(x => x.id !== r.id)].slice(0,100));}}).catch(e => {if(active) setError(String(e));});
    refresh();
    const timer = window.setInterval(refresh, 2000);
    const source = new EventSource(`/runs/${encodeURIComponent(id)}/traces/stream`);
    source.onopen = () => setConnection('연결됨');
    source.onerror = () => setConnection('연결 끊김 · 자동 재연결 중');
    source.addEventListener('trace', event => {
      const trace: Trace = JSON.parse((event as MessageEvent).data);
      if (!active || trace.run_id !== id) return;
      setTraces(old => [...new Map([...old, trace].map(t => [t.seq, t])).values()].sort((a,b) => a.seq-b.seq).slice(-2000));
      if (['interrupt', 'run_end', 'error'].includes(trace.kind)) refresh();
    });
    return () => {active=false; source.close(); clearInterval(timer);};
  }, [id]);
  useEffect(() => {
    if (replay === null || replay >= traces.length) return;
    const timer = setTimeout(() => setReplay(n => n === null ? null : n + 1), 1000/speed);
    return () => clearTimeout(timer);
  }, [replay, speed, traces.length]);
  const visible = replay === null ? traces : traces.slice(0,replay);
  const messages=visible.filter(t=>t.kind==='agent_message');
  const completed = new Set(visible.filter(t => t.kind === 'node_end'||t.kind==='agent_message').map(t => t.agent));
  const waiting = run?.status === 'awaiting_approval' && replay === null;
  const nodes = roles.map((role, i) => ({id: role, position: {x:(i%4)*200,y:Math.floor(i/4)*140}, data: {label: `${roleNames[role]||role}${waiting && role==='approval' ? ' · 승인 대기' : completed.has(role) ? ' ✓' : ''}`}, style: {background: waiting && role==='approval' ? '#fff0c2' : completed.has(role) ? '#d4f0e2' : '#fff', borderColor: '#547369'}}));
  const path = visible.filter(t => t.kind === 'node_end' && roles.includes(t.agent)).map(t => t.agent);
  const edges = [...path.slice(1).map((role, i) => ({id:`path-${i}`,source:path[i],target:role, animated:run?.status==='running'})),...messages.filter(t=>roles.includes(String(t.payload.sender))&&roles.includes(String(t.payload.recipient))).map(t=>({id:`message-${t.seq}`,source:String(t.payload.sender),target:String(t.payload.recipient),animated:run?.status==='running'}))];
  async function start(policy = false) {
    setBusy(true); setError('');
    try {const r = await api<Run>('/scenarios/run',policy ? {id:'policy-research',type:'policy',sim_time:new Date().toISOString(),payload:{goal,scopes:policyScopes}} : scenarios[scenario]); setId(r.id);}
    catch(e) {setError(String(e));} finally {setBusy(false);}
  }
  return <section>
    <p>지역 협업 시나리오에서 분석안 → 근거 검토 → 필요 시 재작성을 확인할 수 있습니다. fake는 통신 시연이며 모델 판단이 아닙니다.</p>
    <div className="toolbar"><label>시나리오 <select value={scenario} onChange={e=>setScenario(Number(e.target.value))}>{scenarios.map((s,i)=><option key={s.id} value={i}>{s.id}</option>)}</select></label><button disabled={busy} onClick={()=>start()}>실행</button>
    <label>실행 이력 <select aria-label="실행 이력" value={id} onChange={e=>setId(e.target.value)}><option value="">선택</option>{runs.map(r=><option key={r.id} value={r.id}>{r.scenario_id} · {r.id.slice(0,8)}</option>)}</select></label></div>
    <fieldset id="policy-task"><legend>Supervisor에게 정책 조사 지시</legend>
      <label>조사 목표 <input value={goal} maxLength={1000} onChange={e=>setGoal(e.target.value)}/></label>
      {Object.entries(scopeNames).map(([scope,name])=><label key={scope}><input type="checkbox" checked={policyScopes.includes(scope)} onChange={e=>setPolicyScopes(old=>e.target.checked?[...old,scope]:old.filter(s=>s!==scope))}/>{name}</label>)}
      <button disabled={busy || !goal.trim() || !policyScopes.length} onClick={()=>start(true)}>정책 조사 위임</button>
      <p>공식 API 등록 정책을 조사합니다. 자격·잔여 정원은 별도 확인이 필요하며 실제 배정은 하지 않습니다. fake는 모델의 행동 시연입니다. 정부24 API 자료는 서버 키 설정에 따라 실제 조회하며, 연결·수집 상태는 정책 탐색에서 확인하세요.</p>
    </fieldset>
    {error && <p role="alert">{error}</p>}
    {!id && <p>시나리오를 실행하거나 이전 실행을 선택하세요.</p>}
    {run && <><div className="card"><strong data-testid="run-status">{statusText[run.status] || run.status}</strong><p data-testid="run-id">{run.id}</p><p>데이터 {run.data_mode} · LLM {run.llm_mode} · 모델 {run.model_version}</p>{run.data_mode==='local' && <p>로컬 데이터: 상세와 캡처를 공개하지 마세요.</p>}<p>SSE {connection}</p></div>
    {visible.filter(t=>t.agent==='policy' && t.kind==='node_end').map(t=><article className="card" key={t.seq} data-testid="policy-result"><h2>정책 조사 결과</h2><p>조사 상태: {String(t.payload.status)} · 담당자 확인 필요</p><pre>{JSON.stringify(t.payload,null,2)}</pre></article>)}
    {!!messages.length&&<section className="card" data-testid="agent-messages"><h2>에이전트 간 전달</h2><ol>{messages.map(t=>{const plan=t.payload.plan as {summary?:string}|undefined;const concerns=t.payload.concerns as string[]|undefined;return <li key={t.seq}><strong>{roleNames[String(t.payload.sender)]||String(t.payload.sender)} → {roleNames[String(t.payload.recipient)]||String(t.payload.recipient)}</strong><p>{String(plan?.summary||concerns?.join(' · ')||t.payload.goal||t.payload.decision||'근거 전달')}</p><button onClick={()=>setDetail(t)}>전달 근거 보기 #{t.seq}</button></li>;})}</ol></section>}
    <div className="graph" aria-label="온라인 실행 그래프"><ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={false} nodesConnectable={false}><Background/><Controls showInteractive={false}/></ReactFlow></div>
    <p>실행 경로: {path.join(' → ') || '대기'}{waiting ? ' → 승인 대기' : ''}</p>
    <aside className="card">오프라인 curator · 카탈로그 검수는 온라인 경로 밖에서 수행합니다.</aside>
    <div className="toolbar"><button disabled={!traces.length} onClick={()=>{setReplay(0);setDetail(undefined);}}>기록 재생</button><button onClick={()=>setReplay(null)}>현재 상태</button><label>재생 배속 <select value={speed} onChange={e=>setSpeed(Number(e.target.value))}>{[1,2,4].map(n=><option key={n} value={n}>{n}×</option>)}</select></label><label>역할 <select value={agent} onChange={e=>setAgent(e.target.value)}>{['all',...roles,'system'].map(a=><option key={a}>{a}</option>)}</select></label></div>
    <p>시뮬레이션 시각: {visible.at(-1)?.sim_ts || '—'} · 재생은 저장된 실제 지연을 바꾸지 않습니다.</p>
    <p>최근 2,000개 수신, 필터 결과 최근 200개 표시. 전체 기록은 <a href={`/runs/${id}/traces?limit=1000`}>trace API</a>에서 seq로 조회합니다.</p>
    <ol className="timeline">{visible.filter(t=>agent==='all'||t.agent===agent).slice(-200).map(t=><li key={t.seq}><button data-testid="trace-row" onClick={()=>setDetail(t)}>#{t.seq} {t.agent} · {t.kind} · {t.latency_ms.toFixed(1)}ms</button></li>)}</ol>
    {detail && <article className="card"><h2>이벤트 상세 #{detail.seq}</h2><p>{detail.run_id} · wall {detail.wall_ts} · sim {detail.sim_ts}</p><p>입력 {detail.tokens_in} / 출력 {detail.tokens_out} tokens · {detail.latency_ms.toFixed(1)}ms</p><pre>{JSON.stringify(detail.payload,null,2)}</pre></article>}</>}
  </section>;
}
