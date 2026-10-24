export type NeedProfile={mapping_status:string;needed_data:string[];next_action:string;observed_factors:Record<string,number>;population_context?:Record<string,number>};
export function NeedEvidence({profile}:{profile?:NeedProfile}){
 if(!profile)return null;
 return <div className="need-evidence"><p>{profile.mapping_status==='index_hypothesis'?'관계 지원 필요는 지수에 따른 조사 가설입니다.':'서비스 욕구를 확정할 근거가 부족합니다.'}</p><p>다음 행동: {profile.next_action}</p><details><summary>욕구 확인에 필요한 자료</summary><ul>{profile.needed_data.map(item=><li key={item}>{item}</li>)}</ul><p>관측 요인은 원천 필드이며 경제·주거·건강 욕구로 환산하지 않습니다.</p>{!!Object.keys(profile.population_context||{}).length&&<p>청년 인구는 성별 공통 참고 자료이며 서비스 수요 인원이 아닙니다.</p>}<pre>{JSON.stringify({factors:profile.observed_factors,population_context:profile.population_context},null,2)}</pre></details></div>;
}
