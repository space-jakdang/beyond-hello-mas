import {useEffect,useState} from 'react';
import {api} from './api';
import {WorkflowEvaluationPanel,WorkflowEvaluationData} from './WorkflowEvaluation';
import {TemporalPanel,CollaborationPanel,Temporal,Paired} from './EvaluationPanels';
type Brief={id:string;created_at:string;data_mode:string;llm_mode:string;status:string;evaluated_scenarios:number;schema_version?:string};
type Summary=Brief&{metrics:Record<string,unknown>;metadata:Record<string,unknown>;uncompleted:string[];limitations:string[];stage_reproducibility:{identical?:boolean|null;repetitions?:number};results:{scenario_id:string;status:string;path_correct:boolean;receipt_ms:number|null}[];workflow?:WorkflowEvaluationData;temporal?:Temporal;collaboration?:Paired};
const suites:Record<string,string>={'1':'기존 실행 평가','2':'60건 계약 검증','3':'월별 합성 예측','4':'에이전트 협업 비교','5':'지역 업무 검증'};
const names:Record<string,string>={path_accuracy:'실행 경로 일치',question_routing:'질문 경로 일치',protocol_stage_accuracy:'합성 개인 계약 일치 (실제 판정 아님)',regional_rule_agreement:'지역 규칙 일치',youth_regional_rule_agreement:'청년 지역 규칙 일치',provided_stage_preservation:'제공 단계 보존',high_stage_handoff:'높은 단계 인계',fixed_phrase_crisis_recall:'고정 위기 표현 탐지',fixed_phrase_false_positive:'고정 혼동 표현 오탐',clinical_person_stage_accuracy:'실제 개인 판정 정확도',llm_response_extraction_accuracy:'LLM 응답 추출 정확도',intervention_suitability_review:'전문가 개입 적합성',outside_catalog_recommendations:'카탈로그 밖 추천',regional_cardinality_errors:'지역 집단 수 오류',cost:'모델 비용',execution_latency:'프로세스 내부 실행 지연'};
function metric(value:unknown){
 if(value===null)return 'N/A';
 if(typeof value==='object'&&value!==null&&'numerator' in value&&'denominator' in value){const v=value as {numerator:number;denominator:number;value:number|null};return `${v.numerator} / ${v.denominator} · ${v.value==null?'N/A':(v.value*100).toFixed(1)+'%'}`;}
 return <pre>{JSON.stringify(value,null,2)}</pre>;
}
export function Evaluation(){
 const [source,setSource]=useState('sample'),[reload,setReload]=useState(0),[reports,setReports]=useState<Brief[]>([]),[selected,setSelected]=useState(''),[summary,setSummary]=useState<Summary>(),[error,setError]=useState('');
 useEffect(()=>{let active=true;setError('');api<Brief[]>(`/reports?source=${source}`).then(rows=>{if(active){setReports(rows);setSelected(id=>rows.some(r=>r.id===id)?id:rows[0]?.id||'');}}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[source,reload]);
 useEffect(()=>{setSummary(undefined);if(!selected)return;let active=true;api<Summary>(`/reports/${selected}?source=${source}`).then(s=>{if(active)setSummary(s);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[selected,source,reload]);
 return <section><p>계약 검증은 규칙대로 실행했는지, 월별 예측은 보지 못한 다음 달을 얼마나 맞혔는지, 협업 비교는 검토의 효과와 추가 비용을 확인합니다.</p>
 <p>개인 판정은 후순위입니다. 합성 데이터 결과를 실제 고립 예측 정확도로 해석하지 않습니다.</p>
 <label>평가 자료 <select style={{maxWidth:'100%'}} value={source} onChange={e=>{setSelected('');setSummary(undefined);setReports([]);setSource(e.target.value);}}><option value="sample">공개 합성 평가 (sample/fake)</option><option value="current">현재 서버 데이터·LLM 모드</option></select></label>
 <button onClick={()=>setReload(n=>n+1)}>평가 결과 새로고침</button>{error&&<p role="alert">{error}</p>}
 {!reports.length&&<p>평가 결과가 없습니다. make eval-v2 / make eval-temporal / make eval-collaboration / make eval-workflow로 생성합니다.</p>}
 <label>평가 실행 <select style={{maxWidth:'100%'}} value={selected} onChange={e=>setSelected(e.target.value)}><option value="">선택</option>{reports.map(r=><option key={r.id} value={r.id}>{suites[r.schema_version||'1']||'기타 평가'} · {r.created_at} · {r.id.slice(0,8)}</option>)}</select></label>
 {summary&&<article className="card"><h2>평가 결과 · {suites[summary.schema_version||'1']||summary.status}</h2><p data-testid="suite-id">{summary.id}</p><p>상태 {summary.status} · 데이터 {summary.data_mode} · LLM {summary.llm_mode} · 전체 분모 <strong data-testid="suite-count">{summary.evaluated_scenarios}</strong></p>
 <p className="mode-banner">{summary.data_mode==='sample'&&summary.llm_mode==='fake'?'합성 평가의 실행·계약·예측 결과입니다.':'현재 데이터·모델 모드에서 저장된 보고서입니다.'} 실제 개인 판정, 실제 고립 예측 성능, 실제 LLM 협업 효과는 별도 검증이 필요합니다.</p>
 <p>동일 입력 재현: {summary.stage_reproducibility.identical===true?'일치':summary.stage_reproducibility.identical===false?'불일치':'미측정'} · {summary.stage_reproducibility.repetitions??0}회. 재현성은 예측 정확도가 아닙니다.</p>
 <p>미완료: {summary.uncompleted.length?summary.uncompleted.join(', '):'없음 (선택한 평가 범위 내)'}</p>
 {summary.workflow&&<WorkflowEvaluationPanel key={summary.id} data={summary.workflow}/>}
 {summary.temporal&&<TemporalPanel key={summary.id} data={summary.temporal}/>}{summary.collaboration&&<CollaborationPanel data={summary.collaboration}/>}
 {!summary.workflow&&!summary.temporal&&!summary.collaboration&&<table><thead><tr><th>지표</th><th>값과 분모</th></tr></thead><tbody>{Object.entries(summary.metrics).map(([name,value])=><tr key={name}><th>{names[name]||name}</th><td>{metric(value)}</td></tr>)}</tbody></table>}
 <ul>{summary.limitations.map((s,i)=><li key={i}>{s}</li>)}</ul><a href={`/reports/${summary.id}?source=${source}`}>원본 summary JSON</a>
 <details><summary>전체 지표·재현성·입력/코드 버전</summary><pre>{JSON.stringify({metrics:summary.metrics,reproducibility:summary.stage_reproducibility,metadata:summary.metadata},null,2)}</pre></details>
 {!!summary.results.length&&<details><summary>시나리오별 결과</summary><table><thead><tr><th>시나리오</th><th>실행</th><th>경로 일치</th><th>수신 확인 지연</th></tr></thead><tbody>{summary.results.map(r=><tr key={r.scenario_id}><td>{r.scenario_id}</td><td>{r.status}</td><td>{String(r.path_correct)}</td><td>{r.receipt_ms==null?'N/A':`${r.receipt_ms.toFixed(1)}ms`}</td></tr>)}</tbody></table></details>}
 </article>}
 </section>;
}
