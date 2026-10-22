import {percent} from './ClassificationQuality';
export type GroundingData={judge_model:string;ragas_version:string;state:string;human_judge_alignment:null;cost_scope:string;cost:{calls:number;reserved_usd:number;known_usd:number;unknown_cost_calls:number};rows:{case_id:string;role:string;source_run_id:string;source_call_key:string;metrics:Record<string,{value:number|null;state:string;reason?:string|null;error_type?:string|null}>}[];limitations:string[]};
const names:Record<string,string>={faithfulness:'근거 충실도',context_precision:'근거 정밀도',context_recall:'근거 재현율'};
export function GroundingQuality({data}:{data:GroundingData}){
 return <section aria-label="RAGAS 근거 평가"><h3>RAGAS 근거 평가</h3><p>RAGAS {data.ragas_version} · 평가 모델 {data.judge_model} · 한국어 독립 사람 평정과의 일치도 미검증</p><p>전체 평가 실행 {data.cost.calls}회 호출 · 비용 확인분 ${data.cost.known_usd.toFixed(5)} · 예약 ${data.cost.reserved_usd.toFixed(5)} · 비용 미확인 {data.cost.unknown_cost_calls}회 (지역 필터와 별개)</p>
 {data.rows.map(r=><article className="card" key={r.case_id+r.source_call_key}><h4>{r.case_id} · {r.role}</h4><div className="evidence-cards">{Object.entries(r.metrics).map(([key,m])=><section key={key}><h4>{names[key]||key}</h4><strong>{m.state==='failed'?'평가 실패':percent(m.value)}</strong>{m.state==='not_evaluated'&&<p>독립 참조 문장 또는 평가 가능한 주장이 필요합니다.</p>}{m.state==='failed'&&<p>실패를 점수 0으로 처리하지 않습니다. {m.error_type}</p>}</section>)}</div><a href={`/observatory?run=${encodeURIComponent(r.source_run_id)}`}>평가한 실제 모델 실행 확인 →</a></article>)}
 <ul>{data.limitations.map(t=><li key={t}>{t}</li>)}</ul></section>;
}
