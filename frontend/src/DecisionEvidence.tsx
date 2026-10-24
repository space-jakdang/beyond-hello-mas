export type CandidateCheck={candidate_status?:string;unknown_conditions?:string[];age_coverage?:string;eligible_age_ranges?:[number,number][]};
export function CandidateConditions({candidate}:{candidate:CandidateCheck}){
 if(!candidate.candidate_status)return null;
 const unknown=[...new Set((candidate.unknown_conditions||[]).map(c=>c==='age'?'해당 연령 일부':c==='unstructured_eligibility'?'지원 대상 원문':c.startsWith('eligibility:')?'지원 자격':'추가 운영 조건'))];
 return <div><p>{candidate.candidate_status==='conditional'?'조건부 검토 후보':'등록 조건 일치'} · 지원 확정 아님</p><p>{candidate.age_coverage==='partial'?'일부 연령만 해당':'원자료 연령 범위 포함'}: {candidate.eligible_age_ranges?.map(([low,high])=>`${low}–${high}세`).join(', ')}</p>{!!unknown.length&&<p>추가 확인: {unknown.join(' · ')}</p>}</div>;
}
export type DecisionEvidenceData={version:string;observation:{evidence_id:string;index_name:string;value:number|null;source_period:string;components:Record<string,unknown>|null};mapping_version:string;provisional_needs:string[];filter_request:Record<string,unknown>|null;catalog_metadata:Record<string,unknown>|null;presented_candidates:({id:string;name:string;needs:string[];source_url?:string|null;collected_at?:string|null;eligibility:string;valid_until?:string|null}&CandidateCheck)[];unknown_conditions:string[];model_reason:string|null};
const reasons:Record<string,string>={inactive_or_expired:'비활성 또는 기한 종료',not_yet_collected:'기준일 이후 수집',jurisdiction:'관할 불일치',age:'연령 범위 불일치',stage:'단계 범위 불일치',intensity:'지원 강도 불일치',needs:'필요 대응 없음',unstructured_eligibility:'지원 자격 확인 필요'};
const needs:Record<string,string>={relationship:'관계 연결',economic:'경제 지원',housing:'주거',employment:'고용',health:'건강',emotional:'정서 지원'};
const unknownConditions:Record<string,string>={individual_eligibility:'개인별 지원 자격',application_acceptance:'신청 접수 여부',remaining_capacity:'남은 지원 규모'};
const needName=(name:string)=>needs[name]||'기타 필요 가설';
export function DecisionEvidence({data,selectedIds,excluded=[],held=false}:{data?:DecisionEvidenceData|null;selectedIds:string[];excluded?:{id:string;reasons:string[]}[];held?:boolean}){
 if(!data)return <p className="muted">이 실행에는 추천 근거 상세가 기록되지 않았습니다.</p>;
 const conditions=data.unknown_conditions||[];
 const modelReason=data.model_reason?.replace(/^fake:\s*/i,'').trim();
 return <details className="decision-evidence"><summary>추천·보류 근거와 미확인 사항</summary>
  <p>관측 근거: {data.observation.index_name} · 값 {data.observation.value??'결측'} · 자료 기간 {data.observation.source_period}</p>
  <p>잠정 필요 가설: {data.provisional_needs.map(needName).join(' · ')||'근거 부족으로 제시하지 않음'}</p>
  <p>개인별 자격·접수 여부·남은 지원 규모는 미확인입니다. 이 결과는 실제 배정이 아닙니다.</p>
  <p>{data.filter_request?'등록 자원의 관할·연령·단계·필요·기준일·자격 조건을 확인했습니다.':'필수 관측이나 통계 검토가 부족해 자원 조건을 확인하지 못했습니다.'}</p>
  {conditions.length>0&&<p><strong>담당자가 확인할 사항:</strong> {conditions.map(c=>unknownConditions[c]||'추가 자격·운영 조건').join(' · ')}</p>}
  {modelReason&&<p>제안 설명{held?' (최종 추천은 보류됨)':''}: {modelReason}</p>}
  {!!data.presented_candidates.length&&<ul>{data.presented_candidates.map(c=><li key={c.id}><strong>{c.name}</strong> · {selectedIds.includes(c.id)?'조건부 추천':held?'최종 추천 보류':'선택되지 않음'}<CandidateConditions candidate={c}/><details><summary>등록된 지원 대상 확인</summary><p>{c.eligibility}</p></details><p>자료 수집일 {c.collected_at||'확인되지 않음'} · 지원 기한 {c.valid_until||'별도 확인 필요'}</p>{c.source_url&&/^https?:\/\//i.test(c.source_url)&&<a href={c.source_url} target="_blank" rel="noreferrer">등록 자원 원문 ↗</a>}</li>)}</ul>}
  {!!excluded.length&&<details><summary>조건에 맞지 않아 제외된 자원 {excluded.length}건</summary><ul>{excluded.map(c=><li key={c.id}>{c.reasons.map(r=>reasons[r]||(r.startsWith('eligibility_unconfirmed:')?'지원 자격 확인 필요':'확인 기준에 맞지 않음')).join(' · ')} <details><summary>자원 식별자와 사유 코드</summary><p>{c.id} · {c.reasons.join(', ')}</p></details></li>)}</ul></details>}
  <details><summary>입력 조건과 원천 코드</summary><p>근거 ID: {data.observation.evidence_id} · 매핑 버전: {data.mapping_version} · 증거 버전: {data.version}</p><p>확인되지 않은 필요 코드: {data.provisional_needs.filter(n=>!needs[n]).join(', ')||'없음'}</p><pre>{JSON.stringify({request:data.filter_request,catalog:data.catalog_metadata,components:data.observation.components},null,2)}</pre></details>
 </details>;
}
