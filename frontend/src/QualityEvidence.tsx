import {useState} from 'react';
import {api} from './api';
import {DecisionEvidence,DecisionEvidenceData} from './DecisionEvidence';
type Evidence={run_id:string|null;reason:string|null;rows:{decision_evidence?:DecisionEvidenceData;selected_ids:string[];excluded:{id:string;reasons:string[]}[];held:boolean}[]};
export function QualityEvidence({reportId,caseId,source}:{reportId:string;caseId:string;source:string}){
 const [result,setResult]=useState<Evidence>(),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const load=async()=>{setBusy(true);try{setResult(await api<Evidence>(`/reports/quality/${reportId}/evidence?case_id=${encodeURIComponent(caseId)}&source=${source}`));}catch{setError('이 사례의 실행 근거를 확인할 수 없습니다.');}finally{setBusy(false);}};
 return <section><button onClick={load} disabled={busy}>{busy?'근거 확인 중…':'이 사례의 추천 근거 조회'}</button>{error&&<p role="alert">{error}</p>}{result&&<>{result.reason&&<p>{result.reason}</p>}{result.run_id&&<a href={`/workspace?run=${encodeURIComponent(result.run_id)}`}>원래 에이전트 실행 보기 →</a>}{result.rows.map((r,i)=><DecisionEvidence key={i} data={r.decision_evidence} selectedIds={r.selected_ids} excluded={r.excluded} held={r.held}/>)}</>}</section>;
}
