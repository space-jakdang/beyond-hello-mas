export type AnalysisPlan={summary:string;priority_evidence_ids:string[]};
export type ReviewRecord={status:string;review_version?:string;revision_check?:string|null;initial_plan?:AnalysisPlan;revised_plan?:AnalysisPlan|null;review_history?:{phase:string;action:string;reason:string}[]};
const clean=(text:string)=>text.replace(/^fake:\s*/i,'').trim();

export function ReviewChanges({review,segments}:{review:ReviewRecord;segments:{evidence_id:string;dong_nm:string}[]}){
 const initial=review.initial_plan,revised=review.revised_plan;
 const names=(ids:string[])=>ids.map(id=>segments.find(row=>row.evidence_id===id)?.dong_nm||'기록된 근거').join(' · ')||'없음';
 const accepted=review.status==='reviewed'&&review.revision_check==='final_statistics_review';
 return <section className="review-changes" aria-label="판단 보완 결과"><h4>판단 보완 결과</h4>
 {!initial?<p>이 실행에는 비교할 분석 전후 기록이 없습니다.</p>:!revised?<p>저장된 분석 보완은 없습니다.{review.status!=='reviewed'&&' 통계 검토를 완료하지 못해 담당자 확인이 필요합니다.'}</p>:<>
 <p>{accepted?'보완한 분석을 통계가 다시 검토해 현재 결과에 반영했습니다.':'보완 초안의 최종 검토를 완료하지 못했습니다. 현재 결과에는 최초 분석을 유지합니다.'}</p>
 {initial.summary!==revised.summary||initial.priority_evidence_ids.join('|')!==revised.priority_evidence_ids.join('|')?<div className="table-scroll"><table><caption>{accepted?'저장된 분석의 실제 변경':'현재 결과에 미반영된 보완 초안과 비교'}</caption><thead><tr><th>항목</th><th>최초 분석</th><th>{accepted?'반영된 분석':'미검토 초안'}</th></tr></thead><tbody>
 {initial.summary!==revised.summary&&<tr><th>분석 요약</th><td>{clean(initial.summary)}</td><td>{clean(revised.summary)}</td></tr>}
 {initial.priority_evidence_ids.join('|')!==revised.priority_evidence_ids.join('|')&&<tr><th>우선 확인 순서</th><td>{names(initial.priority_evidence_ids)}</td><td>{names(revised.priority_evidence_ids)}</td></tr>}
 </tbody></table></div>:<p>보완 요청은 있었지만 저장된 요약과 우선 확인 순서는 같습니다.</p>}
 </>}
 {!!review.review_history?.length&&<details><summary>저장된 검토 사유 확인</summary><ol>{review.review_history.map((item,index)=><li key={index}>{item.phase==='final'?'최종 재검토':'최초 검토'} · {clean(item.reason)}</li>)}</ol></details>}
 <p><strong>다음 행동:</strong> {review.status==='reviewed'?'후보별 미확인 조건과 현장 필요를 확인한 뒤 검토 결정을 남기세요.':'원천 자료와 검토 중단 사유를 확인하고, 필요한 내용을 보완해 새 검토를 요청하세요.'}</p>
 </section>;
}

export type PolicyGap={status:string;search_status:string;next_action:string;recommendation_slot_shortfall:number;field_gap_status:string;absence_established:boolean};
const states:Record<string,string>={insufficient_observation:'관측 자료 보완 필요',needs_unconfirmed:'서비스 필요 확인 전',matching_incomplete:'후보 검토 미완료',unmet_need_hypotheses:'후보가 다루지 못한 필요 가설 있음',no_catalog_candidates:'등록 자원 후보 없음',qualification_unconfirmed:'후보 자격·조건 확인 필요',candidate_coverage:'후보가 필요 가설 범위를 다룸'};
const searches:Record<string,string>={not_requested:'추가 정책 조사 없음',search_failed:'정책 검색 실패',search_incomplete:'정책 검색 범위 확인 미완료',candidates_found:'정책 조사 후보 있음',no_verified_candidates_within_scope:'확인한 검색 범위에서 후보 없음'};
export function PolicyGapSummary({gap}:{gap?:PolicyGap}){
 if(!gap)return null;
 return <div className="policy-gap-summary"><p><strong>{states[gap.status]||'필요·후보 상태 확인 필요'}</strong> · {searches[gap.search_status]||'정책 검색 상태 확인 필요'}</p>
 <p>빈 추천 슬롯 {gap.recommendation_slot_shortfall}개는 실제 서비스 부족을 뜻하지 않습니다. 현장 공백은 미평가입니다.</p>
 <p><strong>다음 행동:</strong> {gap.next_action}</p></div>;
}
