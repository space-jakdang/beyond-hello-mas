export type CandidateCheck={candidate_status?:string;unknown_conditions?:string[];age_coverage?:string;eligible_age_ranges?:[number,number][]};
export function CandidateConditions({candidate}:{candidate:CandidateCheck}){
 if(!candidate.candidate_status)return null;
 const unknown=[...new Set((candidate.unknown_conditions||[]).map(c=>c==='age'?'해당 연령 일부':c==='unstructured_eligibility'?'지원 대상 원문':c==='support_stage'?'지원 단계 해석':c==='support_intensity'?'지원 강도 해석':c.startsWith('eligibility:')?'지원 자격':c))];
 return <div><p>{candidate.candidate_status==='conditional'?'조건부 검토 후보':'등록 조건 일치'} · 지원 확정 아님</p><p>{candidate.age_coverage==='partial'?'일부 연령만 해당':'원자료 연령 범위 포함'}: {candidate.eligible_age_ranges?.map(([low,high])=>`${low}–${high}세`).join(', ')}</p>{!!unknown.length&&<p>추가 확인: {unknown.join(' · ')}</p>}</div>;
}
export type DecisionEvidenceData={version:string;observation:{evidence_id:string;index_name:string;value:number|null;source_period:string;components:Record<string,unknown>|null};mapping_version:string;provisional_needs:string[];filter_request:Record<string,unknown>|null;catalog_metadata:Record<string,unknown>|null;presented_candidates:({id:string;name:string;needs:string[];source_url?:string|null;collected_at?:string|null;eligibility:string;valid_until?:string|null}&CandidateCheck)[];unknown_conditions:string[];model_reason:string|null};
const reasons:Record<string,string>={inactive_or_expired:'비활성 또는 기한 종료',not_yet_collected:'기준일 이후 수집',jurisdiction:'관할 불일치',age:'연령 범위 불일치',stage:'등급 범위 불일치',intensity:'지원 강도 불일치',needs:'욕구 대응 없음',unstructured_eligibility:'지원 자격 구조화 필요'};
export function DecisionEvidence({data,selectedIds,excluded=[],held=false}:{data?:DecisionEvidenceData|null;selectedIds:string[];excluded?:{id:string;reasons:string[]}[];held?:boolean}){
 if(!data)return <p className="muted">이 실행에는 상세 결정 근거가 기록되지 않았습니다.</p>;
 return <details className="decision-evidence"><summary>추천·제외 근거 확인</summary><p>관측 근거 {data.observation.evidence_id} · {data.observation.source_period}</p><p>{data.observation.index_name}: {data.observation.value??'결측'} → 잠정 욕구 {data.provisional_needs.join(', ')||'없음'} ({data.mapping_version})</p><p>개인 자격·접수 여부·잔여 정원은 미확인입니다. 실제 배정이 아닙니다.</p>
 <p>{data.filter_request?'관할·연령·등급·욕구·기준일·등록 자격 조건을 필터로 검사했습니다.':'필수 관측 또는 통계 검토가 부족해 자원 필터를 실행하지 못했습니다.'}</p>
 {data.model_reason&&<p>모델의 선택 설명{held?' (최종 결과는 보류)':''}: {data.model_reason}</p>}
 <ul>{data.presented_candidates.map(c=><li key={c.id}><strong>{c.name}</strong> · {selectedIds.includes(c.id)?'조건부 추천':held?'최종 추천 보류':'모델 미선택'}<CandidateConditions candidate={c}/><p>지원 대상 원문: {c.eligibility}</p><p>수집 {c.collected_at||'미기록'} · 기한 {c.valid_until||'별도 확인'}</p>{c.source_url&&/^https?:\/\//i.test(c.source_url)&&<a href={c.source_url} target="_blank" rel="noreferrer">등록 자원 원문 ↗</a>}</li>)}</ul>
 {!!excluded.length&&<details><summary>필터에서 제외된 자원 {excluded.length}건</summary><ul>{excluded.map(c=><li key={c.id}>{c.id}: {c.reasons.map(r=>reasons[r]||(r.startsWith('eligibility_unconfirmed:')?'자격 미확인: '+r.split(':')[1]:r)).join(' · ')}</li>)}</ul></details>}
 <details><summary>필터 입력과 카탈로그 버전</summary><pre>{JSON.stringify({request:data.filter_request,catalog:data.catalog_metadata},null,2)}</pre></details></details>;
}
