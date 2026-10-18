import {useEffect, useState} from 'react';
import {ReactFlow, Background, Controls} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {api, Run, Trace, scenarios, statusText} from './api';
const roles = ['supervisor', 'classify', 'match', 'approval', 'link'];
export function Observatory() {
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
  const completed = new Set(visible.filter(t => t.kind === 'node_end').map(t => t.agent));
  const waiting = run?.status === 'awaiting_approval' && replay === null;
  const nodes = roles.map((role, i) => ({id: role, position: {x:i*190,y:40}, data: {label: `${role}${waiting && role==='approval' ? ' · 승인 대기' : completed.has(role) ? ' ✓' : ''}`}, style: {background: waiting && role==='approval' ? '#fff0c2' : completed.has(role) ? '#d4f0e2' : '#fff', borderColor: '#547369'}}));
  const path = visible.filter(t => t.kind === 'node_end' && roles.includes(t.agent)).map(t => t.agent);
  const edges = path.slice(1).map((role, i) => ({id:`${i}`,source:path[i],target:role, animated:run?.status==='running'}));
  async function start() {
    setBusy(true); setError('');
    try {const r = await api<Run>('/scenarios/run',scenarios[scenario]); setId(r.id);}
    catch(e) {setError(String(e));} finally {setBusy(false);}
  }
  return <section>
    <p>합성 시나리오 시연 · 온라인 4개 역할과 승인 게이트</p>
    <div className="toolbar"><label>시나리오 <select value={scenario} onChange={e=>setScenario(Number(e.target.value))}>{scenarios.map((s,i)=><option key={s.id} value={i}>{s.id}</option>)}</select></label><button disabled={busy} onClick={start}>실행</button>
    <label>실행 이력 <select aria-label="실행 이력" value={id} onChange={e=>setId(e.target.value)}><option value="">선택</option>{runs.map(r=><option key={r.id} value={r.id}>{r.scenario_id} · {r.id.slice(0,8)}</option>)}</select></label></div>
    {error && <p role="alert">{error}</p>}
    {!id && <p>시나리오를 실행하거나 이전 실행을 선택하세요.</p>}
    {run && <><div className="card"><strong data-testid="run-status">{statusText[run.status] || run.status}</strong><p data-testid="run-id">{run.id}</p><p>데이터 {run.data_mode} · LLM {run.llm_mode} · 모델 {run.model_version}</p>{run.data_mode==='local' && <p>로컬 데이터: 상세와 캡처를 공개하지 마세요.</p>}<p>SSE {connection}</p></div>
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
