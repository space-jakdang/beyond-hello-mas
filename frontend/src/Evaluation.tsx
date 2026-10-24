import {AlternativeQuality} from './AlternativeQuality';
import {useEffect,useState} from 'react';
import {api} from './api';
import {QualityEvaluation} from './QualityEvaluation';
import {WorkflowEvaluationPanel,WorkflowEvaluationData} from './WorkflowEvaluation';
import {TemporalPanel,CollaborationPanel,Temporal,Paired} from './EvaluationPanels';
import {ApiErrorNotice} from './ApiErrorNotice';
import {dataModeLabel,llmModeLabel} from './modeLabels';
type Brief={id:string;created_at:string;data_mode:string;llm_mode:string;status:string;evaluated_scenarios:number;schema_version?:string};
type Summary=Brief&{metrics:Record<string,unknown>;metadata:Record<string,unknown>;uncompleted:string[];limitations:string[];stage_reproducibility:{identical?:boolean|null;repetitions?:number};results:{scenario_id:string;status:string;path_correct:boolean;receipt_ms:number|null}[];workflow?:WorkflowEvaluationData;temporal?:Temporal;collaboration?:Paired};
const suites:Record<string,string>={'1':'기존 실행 평가','2':'60건 계약 검증','3':'월별 합성 예측','4':'에이전트 협업 비교','5':'지역 업무 검증'};
const reportStatuses:Record<string,string>={completed:'완료',executed:'완료',executed_protocol:'프로토콜 평가 완료',executed_synthetic_forecast:'합성 예측 평가 완료',executed_collaboration_protocol:'협업 비교 완료',contract_passed:'계약 검사 통과',contract_failed:'계약 검사 미통과',rejected:'반려',partial:'일부 항목 미완료',failed:'평가 실패',not_evaluated:'미평가'};
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
 return <section><aside className="mode-banner" aria-label="개발·연구 평가 안내"><strong>개발·연구용 검증 화면</strong><p>이 결과는 규칙과 소프트웨어 계약을 점검합니다. 실제 개인 판정의 정확도나 지역 서비스 효과를 입증하지 않습니다.</p></aside><p>계약 검증은 규칙대로 실행했는지, 월별 예측은 보지 못한 다음 달을 얼마나 맞혔는지, 협업 비교는 검토의 효과와 추가 비용을 확인합니다.</p>
 <p>개인 판정은 후순위입니다. 합성 데이터 결과를 실제 고립 예측 정확도로 해석하지 않습니다.</p>
 <label>평가 자료 <select style={{maxWidth:'100%'}} value={source} onChange={e=>{setSelected('');setSummary(undefined);setReports([]);setSource(e.target.value);}}><option value="sample">공개 합성 평가</option><option value="current">현재 서버 자료·모델 설정</option></select></label>
 <button onClick={()=>setReload(n=>n+1)}>평가 결과 새로고침</button>{error&&<ApiErrorNotice message="평가 결과를 불러오지 못했습니다. 연결 상태를 확인하고 다시 새로고침하세요." detail={error}/>}
 <AlternativeQuality/><QualityEvaluation key={source} source={source} reload={reload}/><h2>개발 검증과 기존 평가 보고서</h2>
 {!reports.length&&!error&&<p>평가 결과가 없습니다. make eval-v2 / make eval-temporal / make eval-collaboration / make eval-workflow로 생성합니다.</p>}
 <label>평가 실행 <select style={{maxWidth:'100%'}} value={selected} onChange={e=>setSelected(e.target.value)}><option value="">선택</option>{reports.map(r=><option key={r.id} value={r.id}>{suites[r.schema_version||'1']||'기타 평가'} · {r.created_at} · {r.id.slice(0,8)}</option>)}</select></label>
 {summary&&<article className="card"><h2>평가 결과 · {suites[summary.schema_version||'1']||'기타 평가'}</h2><p data-testid="suite-id">{summary.id}</p><p>상태 {reportStatuses[summary.status]||'상태 확인 필요'} · 자료 {dataModeLabel(summary.data_mode)} · 모델 {llmModeLabel(summary.llm_mode)} · 전체 분모 <strong data-testid="suite-count">{summary.evaluated_scenarios}</strong></p>
 <p className="mode-banner">자료는 {summary.data_mode==='sample'?'합성 평가':summary.data_mode==='local'?'현재 서버 자료':'확인되지 않은 모드'}이고, 모델은 {summary.llm_mode==='fake'?'정해진 테스트 응답':summary.llm_mode==='live'?'실제 모델 호출 설정':'실행 방식 확인 필요'}입니다. 실제 개인 판정, 실제 고립 예측 성능, 실제 LLM 협업 효과는 별도 검증이 필요합니다.</p>
 <section aria-label="평가 핵심 요약" className="evidence-cards"><section><h3>보고서 평가 분모</h3><strong>{summary.evaluated_scenarios}</strong><p>반복·기간을 포함할 수 있으며 독립 사례 수와 다릅니다.</p></section><section><h3>미완료 항목</h3><strong>{summary.uncompleted.length}</strong><p>선택한 보고서 범위 기준</p></section><section><h3>동일 입력 재현</h3><strong>{summary.stage_reproducibility.identical===true?'일치':summary.stage_reproducibility.identical===false?'불일치':'미측정'}</strong><p>{summary.stage_reproducibility.repetitions??0}회 · 정확도와 별개</p></section></section>
 {summary.workflow&&<section aria-label="지역 업무 계약 요약" className="evidence-cards"><section><h3>합성 계약 검사</h3><strong>{summary.workflow.contract_passed?'통과':'미통과'}</strong><p>실제 분류 타당성·전문가 자원 적합성은 미측정</p></section><section><h3>자원 조건 위반</h3><strong>{summary.workflow.contract.resource_constraints.violations}</strong><p>합성 추천 {summary.workflow.contract.resource_constraints.recommended}건 기준</p></section></section>}
 {summary.temporal&&<section aria-label="합성 미래 예측 요약" className="evidence-cards">{[['last_value','직전 관측 유지'],['trend','최근 관측 추세']].map(([key,label])=>{const m=summary.metrics[key] as {mae:number|null;predicted:number;count:number}|undefined;return m&&<section key={key}><h3>{label} · MAE</h3><strong>{m.mae===null?'미측정':m.mae.toFixed(3)}</strong><p>예측 가능 {m.predicted} / {m.count} · 보고서 전체 seed·기간</p><p>작을수록 오차가 작습니다. 실제 고립 예측 성능은 아닙니다.</p></section>;})}</section>}
 <p>미완료: {summary.uncompleted.length?summary.uncompleted.join(', '):'없음 (선택한 평가 범위 내)'}</p>
 {summary.workflow&&<WorkflowEvaluationPanel key={summary.id} data={summary.workflow}/>}
 {summary.temporal&&<TemporalPanel key={summary.id} data={summary.temporal}/>}{summary.collaboration&&<CollaborationPanel data={summary.collaboration}/>}
 {!summary.workflow&&!summary.temporal&&!summary.collaboration&&<div className="table-scroll"><table><thead><tr><th>지표</th><th>값과 분모</th></tr></thead><tbody>{Object.entries(summary.metrics).map(([name,value])=><tr key={name}><th>{names[name]||name}</th><td>{metric(value)}</td></tr>)}</tbody></table></div>}
 <ul>{summary.limitations.map((s,i)=><li key={i}>{s}</li>)}</ul><a href={`/reports/${summary.id}?source=${source}`}>원본 summary JSON</a>
 <details><summary>전체 지표·재현성·입력/코드 버전</summary><pre>{JSON.stringify({status:summary.status,data_mode:summary.data_mode,llm_mode:summary.llm_mode,metrics:summary.metrics,reproducibility:summary.stage_reproducibility,metadata:summary.metadata},null,2)}</pre></details>
 {!!summary.results.length&&<details><summary>시나리오별 결과</summary><div className="table-scroll"><table><thead><tr><th>시나리오</th><th>실행</th><th>경로 일치</th><th>수신 확인 지연</th></tr></thead><tbody>{summary.results.map(r=><tr key={r.scenario_id}><td>{r.scenario_id}</td><td>{reportStatuses[r.status]||'상태 확인 필요'}</td><td>{String(r.path_correct)}</td><td>{r.receipt_ms==null?'N/A':`${r.receipt_ms.toFixed(1)}ms`}</td></tr>)}</tbody></table></div></details>}
 </article>}
 </section>;
}
