export type Insights={items:{evidence_id:string;dong_nm:string;question:string;comparison:{peer_count:number;peer_median:number|null;risk_direction_difference:number|null;unit?:string;source_period?:string;source_bands?:Record<string,string[]>};measured_need_signals:string[];policy_implication:string;missing_evidence:string[];limitations:string[]}[]};
const signalNames:Record<string,string>={relationship:'관계 연결',economic:'경제 지원',housing:'주거',employment:'고용',health:'건강',emotional:'정서 지원',activity_deficit:'활동 부족'};
export function PolicyInsights({data,evidenceIds}:{data:Insights;evidenceIds:string[]}){
 return <section aria-label="정책 판단 참고"><h3>정책 판단 참고</h3>{data.items.filter(i=>evidenceIds.includes(i.evidence_id)).map(i=>{
  const comparable=i.comparison.risk_direction_difference!==null;
  return <article className="card" key={i.evidence_id}><h4>{i.dong_nm} · {i.question}</h4>
   <p>{comparable?`같은 지수·대상·기간으로 비교 가능한 다른 동 ${i.comparison.peer_count}곳의 자료가 있습니다.`:'같은 기준으로 비교할 자료가 충분하지 않습니다.'}</p>
   <p><strong>검토 제안</strong> · {i.policy_implication}</p><p className="muted">비교값은 위험 확률이나 인과 효과가 아닙니다.</p>
   {i.measured_need_signals.length>0&&<p>자료에서 관측한 요인: {i.measured_need_signals.map(n=>signalNames[n]||'기타 측정 요인').join(' · ')}</p>}
   <p><strong>추가 확인</strong> · {i.missing_evidence.join(' · ')||'별도 확인 항목 없음'}</p>
   <details><summary>비교 수치와 해석 한계</summary>
    <p>원천 지수 차이: {i.comparison.risk_direction_difference?.toFixed(3)??'산출하지 않음'} · 비교군 중앙값: {i.comparison.peer_median?.toFixed(3)??'산출하지 않음'} · 비교 가능한 동: {i.comparison.peer_count}</p>
    <p>원천 지수 단위이며 위험 확률이나 인과 효과가 아닙니다.</p>
    {i.comparison.source_period&&<p>자료 기간: {i.comparison.source_period}</p>}
    {i.comparison.source_bands&&Object.entries(i.comparison.source_bands).map(([source,bands])=><p key={source}>대상 범위({source}): {bands.join(', ')}</p>)}
    {i.measured_need_signals.some(n=>!signalNames[n])&&<p>원천 요인 코드: {i.measured_need_signals.filter(n=>!signalNames[n]).join(', ')}</p>}
    {i.limitations.map(t=><p key={t}>{t}</p>)}
    <p>근거 ID: {i.evidence_id}</p>
   </details>
  </article>;
 })}</section>;
}
