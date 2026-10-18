import {useEffect,useState} from 'react';
import {api} from './api';
type Brief={id:string;created_at:string;data_mode:string;llm_mode:string;status:string;evaluated_scenarios:number};
type Summary=Brief&{schema_version?:string;metrics:Record<string,unknown>;metadata:Record<string,unknown>;uncompleted:string[];limitations:string[];stage_reproducibility:unknown;results:{scenario_id:string;status:string;path_correct:boolean;receipt_ms:number|null}[]};
export function Evaluation(){
  const [reports,setReports]=useState<Brief[]>([]),[selected,setSelected]=useState(''),[summary,setSummary]=useState<Summary>(),[error,setError]=useState('');
  function refresh(){api<Brief[]>('/reports').then(rows=>{setReports(rows);setSelected(id=>id||rows[0]?.id||'');}).catch(e=>setError(String(e)));}
  useEffect(refresh,[]);
  useEffect(()=>{setSummary(undefined);if(!selected)return;let active=true;api<Summary>(`/reports/${selected}`).then(s=>{if(active)setSummary(s);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[selected]);
  return <section><p>make eval / make eval-v2로 만든 결과 · 현재 서버와 같은 데이터/LLM 모드만 표시합니다.</p><button onClick={refresh}>평가 결과 새로고침</button>{error&&<p role="alert">{error}</p>}
    {!reports.length&&<p>평가 결과가 없습니다. make eval-v2로 합성 계약 평가를 실행하세요. v1 척도 평가는 make eval과 MCP 설정이 필요합니다.</p>}
    <label>평가 실행 <select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">선택</option>{reports.map(r=><option key={r.id} value={r.id}>{r.created_at} · {r.status} · {r.id.slice(0,8)}</option>)}</select></label>
    {summary&&<article className="card"><h2>평가 결과 · {summary.status}</h2><p data-testid="suite-id">{summary.id}</p><p>데이터 {summary.data_mode} · LLM {summary.llm_mode} · 전체 분모 <strong data-testid="suite-count">{summary.evaluated_scenarios}</strong></p>{summary.schema_version==='2'&&<p className="mode-banner">합성 계약 검증 결과입니다. 실제 개인 판정 정확도와 LLM 응답 추출은 미검증이며 N/A입니다.</p>}<p>fake 결과는 모델 성능 평가가 아닙니다. 개발 정답은 독립 검수 전이며, N/A와 누락을 0점 지연으로 해석하지 마세요.</p><p>미완료: {summary.uncompleted.join(', ')}</p><a href={`/reports/${summary.id}`}>원본 summary JSON</a>
    <table><thead><tr><th>지표</th><th>값과 분모</th></tr></thead><tbody>{Object.entries(summary.metrics).map(([name,value])=><tr key={name}><th>{name}</th><td><pre>{JSON.stringify(value,null,2)}</pre></td></tr>)}</tbody></table>
    <h3>단계·결과 재현성</h3><pre>{JSON.stringify(summary.stage_reproducibility,null,2)}</pre><h3>입력·코드·가격 버전</h3><pre>{JSON.stringify(summary.metadata,null,2)}</pre>
    <h3>시나리오별 결과</h3><table><thead><tr><th>시나리오</th><th>실행</th><th>경로 일치</th><th>수신 확인 지연</th></tr></thead><tbody>{summary.results.map(r=><tr key={r.scenario_id}><td>{r.scenario_id}</td><td>{r.status}</td><td>{String(r.path_correct)}</td><td>{r.receipt_ms===null?'N/A':`${r.receipt_ms.toFixed(1)}ms`}</td></tr>)}</tbody></table><p>{summary.limitations.join(' · ')}</p></article>}
  </section>;
}
