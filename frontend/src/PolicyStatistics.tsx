export type PolicyNeeds={cohorts:{cohort_id:string;index_name:string;source_period:string;total_segments:number;observed_segments:number;missing_segments:number;priority_segments:number;priority_share:number|null;need_counts:Record<string,number>;joint_needs:{needs:string[];segments:number}[]}[];profiles:{evidence_id:string;dong_nm:string;comparable_segments:number;priority_midrank:number|null;base_stage_stable:boolean|null;needs:string[];need_basis:string;needed_data:string[]}[];limitations:string[]};
const names:Record<string,string>={relationship:'관계 연결',economic:'경제 지원',housing:'주거',employment:'고용',health:'건강',emotional:'정서 지원'};
const basisNames:Record<string,string>={observed_components_and_provisional_mapping:'관측 요인과 잠정 매핑을 함께 살펴봅니다.',index_proxy_only:'지수만 있어 관계 지원 가설로 제한합니다.',insufficient_evidence:'관측 근거가 부족해 필요 가설을 제시하지 않습니다.'};
const needName=(name:string)=>names[name]||'기타 필요 가설';
export function PolicyStatistics({data,evidenceIds}:{data:PolicyNeeds;evidenceIds?:string[]}){
 const profiles=data.profiles.filter(p=>!evidenceIds||evidenceIds.includes(p.evidence_id));
 return <section aria-label="정책 판단 참고 통계"><h3>정책 판단 참고 통계</h3><p>분모는 선택한 동·집단 수입니다. 주민 수요 인원이나 고립 유병률이 아닙니다.</p>
  {data.cohorts.map(c=><article className="card" key={c.cohort_id}><h4>선택 자료 집단 · 원천 기간 {c.source_period}</h4><p>우선 확인 단계 {c.priority_segments}/{c.observed_segments}집단 · 단계 미산출 {c.missing_segments}/{c.total_segments}집단</p>
   <ul>{Object.entries(c.need_counts).map(([n,count])=><li key={n}>{needName(n)} 가설: {count}/{c.observed_segments}집단</li>)}</ul>
   <p>함께 관측된 필요: {c.joint_needs.map(p=>`${p.needs.map(needName).join(' + ')} ${p.segments}집단`).join(' · ')||'없음 또는 요인 자료 부족'}</p>
   <details><summary>지수·원천 코드</summary><p>지수 식별자: {c.index_name} · 자료 집단 ID: {c.cohort_id}</p><p>확인되지 않은 필요 코드: {[...Object.keys(c.need_counts),...c.joint_needs.flatMap(p=>p.needs)].filter(n=>!names[n]).filter((n,i,a)=>a.indexOf(n)===i).join(', ')||'없음'}</p></details>
  </article>)}
  {profiles.map(p=><details key={p.evidence_id}><summary>{p.dong_nm} 근거 · {p.needs.map(needName).join(', ')||'필요 가설 없음'}</summary><p>비교 가능한 집단 {p.comparable_segments}개 · {basisNames[p.need_basis]||'근거 해석 상태를 확인할 수 없습니다.'}</p><p>단계 민감도: {p.base_stage_stable===null?'미평가':p.base_stage_stable?'±0.01 변형에도 유지':'±0.01 변형 시 달라질 수 있음'}.</p><p>추가 확인 자료: {p.needed_data.join(' · ')||'없음'}</p><p>등급 중간순위: {p.priority_midrank===null?'표본 부족':`${p.priority_midrank.toFixed(3)} (0~1)`} · 근거 ID: {p.evidence_id}</p><details><summary>원천 필요 코드</summary><p>{p.needs.filter(n=>!names[n]).join(', ')||'확인되지 않은 코드 없음'} · 매핑 상태: {p.need_basis}</p></details></details>)}
  <details><summary>통계 해석 시 확인할 한계</summary><ul>{data.limitations.map(t=><li key={t}>{t}</li>)}</ul></details>
 </section>;
}
