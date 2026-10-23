import type {Alternative} from './PolicyAlternatives';
export function PolicyAdaptation({alternative:a}:{alternative:Alternative}){
 if(!a.design_checks)return null;
 return <section aria-label="지역 맞춤 설계 근거"><p><strong>{a.design_checks.status==='structured_draft'?'지역 근거·사례·평가 설계 연결됨':'설계 근거 보완 필요'}</strong> · 효과·실행 가능성 미검증</p>
 {a.design_checks.gaps.length>0&&<ul>{a.design_checks.gaps.map(g=><li key={g}>{g}</li>)}</ul>}
 <details><summary>원 정책에서 무엇을 바꾸나요?</summary>{a.source_elements?.map((e,i)=><blockquote key={i}><p>{e.quote}</p><small>{e.policy_id} · {e.field}</small></blockquote>)}{a.adaptations?.map((p,i)=><dl key={i}><dt>참고 정책</dt><dd>{p.source_policy_ids.join(', ')}</dd><dt>우리 지역과의 차이</dt><dd>{p.local_difference}</dd><dt>현지 변경안</dt><dd>{p.proposed_change}</dd><dt>현장 확인</dt><dd>{p.verification_needed.join(' · ')}</dd></dl>)}</details>
 {a.evaluation_design&&<details><summary>어떻게 효과를 확인하나요?</summary><dl>{Object.entries({outcome:'관찰할 결과',baseline_needed:'필요 기준선',comparison_method:'비교 방법',observation_period:'제안 관측 기간',success_criterion_to_agree:'합의할 성공 기준',stop_criterion_to_agree:'합의할 중단 기준'}).map(([key,label])=><div key={key}><dt>{label}</dt><dd>{a.evaluation_design![key as keyof NonNullable<Alternative['evaluation_design']>]}</dd></div>)}</dl></details>}
 </section>;
}
