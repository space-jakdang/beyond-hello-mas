const metricNames:Record<string,string>={S1:'강남 청년 지표',v3:'춘천 청년 지표',G_seoul:'서울 제공 비교 지표',G_gangnam_rank:'강남구 안 동 순위 지표',G_chuncheon:'춘천 집단 비교 지표'};
const sourceNames:Record<string,string>={sk_gangnam_s1:'강남 청년 지표 자료',seoul_telecom:'통신 자료',kosis:'통계청 자료',sk_chuncheon:'춘천 청년 지표 자료',social_integration:'사회통합 자료',welfare_panel:'복지패널 자료',kyps:'청년패널 자료',card:'주간 카드 자료',synthetic:'합성 자료','synthetic-generator-3':'합성 자료 생성기'};
const ageBandNames:Record<string,string>={'19–29':'19~29세','19–34':'19~34세','20–34':'20~34세','30–39':'30~39세','35–49':'35~49세','40–49':'40~49세','50–59':'50~59세','50–64':'50~64세','60+':'60세 이상','60plus':'60세 이상','65+':'65세 이상','20s':'20대','30s':'30대','40s':'40대','50s':'50대'};
const flagNames:Record<string,string>={regions_not_comparable:'지역 간 수치를 직접 비교할 수 없음',period_aggregate:'월별 관측이 아닌 기간 집계',small_population:'기준 인구가 적어 해석에 주의 필요',index_not_sex_specific:'성별별로 산출한 지표가 아님',academy_area:'학원가 특성의 영향이 포함될 수 있음',welfare_rate_2017:'복지율 자료는 2017년 기준',two_branches_agree:'두 자료 갈래의 방향이 일치함',missing:'원자료 값 없음',blind:'자료 추가 확인 필요'};

export const metricName=(code:string)=>metricNames[code]??'지역 지표';
export const sourceName=(code:string)=>sourceNames[code]??'자료 출처 확인 필요';
export const ageBandName=(band:string)=>ageBandNames[band]??'연령 범위 확인 필요';
export const sourceBandsText=(bands:Record<string,string[]>)=>Object.entries(bands).map(([source,ages])=>`${sourceName(source)}: ${ages.map(ageBandName).join(', ')}`).join(' · ')||'연령 범위 확인 필요';
export const periodName=(period:string)=>{
 if(period==='기간 집계')return '월별 관측이 아닌 기간 집계';
 const delivered=period.match(/^(\d{4})-(\d{2})-(\d{2})/);
 if(delivered)return `${delivered[1]}년 ${Number(delivered[2])}월 ${Number(delivered[3])}일 ${period.includes('전달 집계')?'전달 자료':'자료 기준'}${period.includes('월별 관측 아님')?' · 월별 관측 아님':''}`;
 const month=period.match(/^(\d{4})-(\d{2})/);
 return month?`${month[1]}년 ${Number(month[2])}월`:'자료 기간 확인 필요';
};
export const flagName=(flag:string)=>flagNames[flag]??'원자료 추가 확인 필요';
export const weeklyMetricName=(code:string)=>code==='T1b'||code==='R1'?`주간 지표 코드 ${code}`:'주간 카드 지표';
export const signalName=(signal:string,ratio:number|null)=>ratio===null?'비교 기준이 없어 신호를 계산하지 않았습니다.':({none:'경보 없음',weak:'약한 변화 신호',strong:'강한 변화 신호'} as Record<string,string>)[signal]??'상태 확인 필요';
export const ratioName=(ratio:number|null)=>{
 if(ratio===null)return '기준선 없음';
 const change=(ratio-1)*100;
 return Math.abs(change)<.05?`기준선과 거의 같음 (${ratio.toFixed(3)}배)`:`${ratio.toFixed(3)}배 · 기준보다 ${Math.abs(change).toFixed(1)}% ${ratio<1?'낮음':'높음'}`;
};
