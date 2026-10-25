import {MapView,colors} from './Neighborhoods';
import {Analysis,Dong} from './neighborhoodData';
import {metricName} from './groupCopy';

type CardEvidence={source_age_band:string;baseline_status:'unavailable'|'observed';v_ratio:number|null;n_ratio:number|null;v_stage:number;n_stage:number;alarm_stage:number};
type RegionalGroup={dataset_version:string;source_region:string;sgg:string;dong_cd:string;dong_nm:string;source_dong_name:string;sex:'M'|'F';source_age_band:string;frame:string;source_bands:Record<string,string[]>;source_stage:number;source_stage_label:string;assessment_status:'assessed'|'small_population_hold'|'insufficient_evidence';base_stage:number|null;card_week:string;card_source_age_bands:string[];card_evidence:CardEvidence[];card_alarm_stage:number|null;card_alarm_status:'baseline_unavailable'|'none'|'weak'|'strong';stage_adjustment:number;final_stage:number|null;final_stage_label:string;priority_group:string|null;weakness_count:number;population:number;reason:string;structural_risk_ratio:number|null;priority_rank:number};
type CardSignal=CardEvidence&{source_region:string;sex:'M'|'F';week:string};
export type RegionalGroupsV4Data=Pick<Analysis,'data_mode'|'neighborhoods'|'geometry'|'geography'|'coverage'>&{segments:RegionalGroup[];period_aggregate:true;weekly:{selected_week:string;signals:CardSignal[]};metadata:{workflow_version:'regional-workflow-2';methodology_version:string;dataset_version:string;selected_week:string;input_schema_version:number;input_hash:string;weekly_scope:string;source:{source:string;sha256:string};card_source:{source:string;sha256:string}}};
export const isRegionalGroupsV4=(data:unknown):data is RegionalGroupsV4Data=>!!data&&typeof data==='object'&&(data as RegionalGroupsV4Data).metadata?.workflow_version==='regional-workflow-2';

const districtName=(sgg:string)=>sgg==='11230'?'강남구':'춘천시';
const regionKey=(sgg:string)=>sgg==='11230'?'강남':'춘천';
const sexName=(sex:string)=>sex==='M'?'남성':'여성';
const statusText=(row:RegionalGroup|undefined)=>!row?'자료 없음':row.assessment_status==='insufficient_evidence'?'판정 근거 부족 (−1)':row.assessment_status==='small_population_hold'?'소규모 인구 보류 (0)':`${row.final_stage_label} · ${row.final_stage}단계`;
const statusColor=(row:RegionalGroup|undefined)=>!row?colors[0]:row.assessment_status==='insufficient_evidence'?'#b6a6c9':row.assessment_status==='small_population_hold'?'#efc75e':colors[row.final_stage??0];
const alarmText=(row:RegionalGroup)=>{const statuses=row.card_evidence.map(e=>e.baseline_status);const label=({baseline_unavailable:'기준선 없음 · 신호 미산출',none:'경보 없음',weak:'약한 경보',strong:'강한 경보'} as Record<string,string>)[row.card_alarm_status];return statuses.includes('observed')&&statuses.includes('unavailable')?`부분 기준선 · ${label}`:label;};
const cardStatus=(row:CardSignal)=>row.baseline_status==='unavailable'?'기준선 없음 · 신호 미산출':row.alarm_stage===2?'강한 경보':row.alarm_stage===1?'약한 경보':'경보 없음';
const ratio=(value:number|null)=>value===null?'기준선 없음':`${value.toFixed(3)}배`;

export function RegionalGroupsV4({data,selection,onSelect}:{data:RegionalGroupsV4Data;selection:Record<string,string>;onSelect:(patch:Record<string,string>)=>void}){
 const region=['11230','32010'].includes(selection.region)?selection.region:'11230';
 const sex=selection.sex==='M'||selection.sex==='F'?selection.sex:'all';
 const ages=[...new Set(data.segments.filter(r=>r.sgg===region).map(r=>r.source_age_band))];
 const sourceAge=selection.source_age_band||selection.age;
 const age=sourceAge&&ages.includes(sourceAge)?sourceAge:'all';
 const weeks=[...new Set(data.weekly.signals.map(r=>r.week))].sort();
 const selectedWeek=selection.card_week??selection.week;
 const week=weeks.includes(selectedWeek)?selectedWeek:data.metadata.selected_week;
 const dongs=data.neighborhoods.filter(d=>d.sgg===region);
 const dong=dongs.some(d=>d.dong_cd===selection.dong)?selection.dong:dongs[0]?.dong_cd||'';
 const cohorts=data.segments.filter(r=>r.sgg===region&&(age==='all'||r.source_age_band===age)&&(sex==='all'||r.sex===sex));
 const selected=cohorts.filter(r=>r.dong_cd===dong);
 const sexes=sex==='all'?['M','F'] as const:[sex] as const;
 const link=(groupSex:string,band:string,dongCode:string)=>new URLSearchParams({workflow_version:'regional-workflow-2',region,sex:groupSex,source_age_band:band,dong:dongCode,card_week:week}).toString();
 const cards=data.weekly.signals.filter(r=>r.source_region===regionKey(region)&&r.week===week&&(sex==='all'||r.sex===sex)&&(age==='all'||r.source_age_band===age||region==='32010'&&age==='60대+'&&['60대','70대+'].includes(r.source_age_band)));
 const mapSummary=(groupSex:string)=>Object.fromEntries(dongs.map(d=>{const row=cohorts.find(r=>r.dong_cd===d.dong_cd&&r.sex===groupSex);return [d.dong_cd,{label:statusText(row),color:statusColor(row)}];}));
 const detailLink=(row:RegionalGroup)=>`/workspace?${link(row.sex,row.source_age_band,row.dong_cd)}`;
 return <section className="neighborhoods" aria-label="전 연령 원천 집단 분석">
  <p className="mode-banner">{data.data_mode==='local'?'실제 지역 자료':'합성 테스트 자료'} · {data.metadata.dataset_version} · 2025년 기간 집계 · 카드 기준 주 {week} · {districtName(region)} · 우선 확인 순서는 개인 진단·위험률이 아닙니다.</p>
  <p className="muted">연령은 원천 자료의 칸을 그대로 선택합니다. 청년·중년·장년·노년은 설명용 표시 틀이며 서로 다른 원천 연령을 합치지 않습니다. 강남과 춘천의 값·단계는 직접 비교할 수 없습니다.</p>
  <div className="toolbar"><label>지역 <select aria-label="지역" value={region} onChange={e=>onSelect({region:e.target.value,source_age_band:'all',age:'all'})}><option value="11230">강남구</option><option value="32010">춘천시</option></select></label>
   <label>성별 <select aria-label="성별" value={sex} onChange={e=>onSelect({sex:e.target.value})}><option value="M">남성</option><option value="F">여성</option><option value="all">전체 성별</option></select></label>
   <label>원천 연령 <select aria-label="원천 연령" value={age} onChange={e=>onSelect({source_age_band:e.target.value,age:e.target.value})}><option value="all">전체 원천 연령</option>{ages.map(a=><option key={a}>{a}</option>)}</select></label>
   <label>카드 관측 주 <select aria-label="카드 관측 주" value={week} onChange={e=>onSelect({week:e.target.value,card_week:e.target.value})}>{weeks.map(w=><option key={w}>{w}</option>)}</select></label>
   <button onClick={()=>location.reload()}>분석 새로고침</button>
  </div>
  {age==='all'?<section className="card" aria-label="원천 연령별 집단 근거"><h2>{districtName(region)} · 원천 연령별 집단 근거</h2><p>집단별 원천 단계, 카드 경보, 최종 단계와 기준 주를 그대로 표시합니다. 값이 없는 집단을 다른 연령으로 채우지 않습니다.</p><div className="table-scroll" tabIndex={0} role="group" aria-label="원천 연령별 표 가로 스크롤"><table><thead><tr><th>동</th><th>성별</th><th>원천 연령</th><th>표시 틀</th><th>원천 단계</th><th>카드 경보</th><th>최종 단계</th><th>찾아갈 순서</th></tr></thead><tbody>{dongs.flatMap(d=>sexes.flatMap(s=>ages.map(a=>{const row=cohorts.find(r=>r.dong_cd===d.dong_cd&&r.sex===s&&r.source_age_band===a);return <tr key={`${d.dong_cd}-${s}-${a}`}><th><button aria-pressed={dong===d.dong_cd} onClick={()=>onSelect({dong:d.dong_cd})}>{d.dong_nm}</button></th><td>{sexName(s)}</td><td>{a}</td><td>{row?.frame??'자료 없음'}</td><td>{row?`${row.source_stage_label} (${row.source_stage})`:'자료 없음'}</td><td>{row?alarmText(row):'자료 없음'}</td><td>{row?statusText(row):'자료 없음'}</td><td>{row?`우선 ${row.priority_rank}번`:'자료 없음'}</td></tr>})))}</tbody></table></div></section>:<>
   <div className="map-legend" aria-label="단계와 상태 범례"><span><i style={{background:'#b6a6c9'}}/>판정 근거 부족 (−1)</span><span><i style={{background:'#efc75e'}}/>소규모 인구 보류 (0)</span>{[1,2,3,4,5].map(n=><span key={n}><i style={{background:colors[n]}}/>{n}단계</span>)}<span><i style={{background:colors[0]}}/>자료 없음</span></div>
   {sexes.map(s=>{const own=cohorts.filter(r=>r.sex===s),summary=mapSummary(s);return <section className="card" aria-label={`${sexName(s)} 원천 연령 결과`} key={s}><h2>{districtName(region)} · {sexName(s)} · {age} · 표시 틀 {own[0]?.frame??'확인 필요'}</h2>
    <div className="map-layout"><article className="card"><MapView data={data} dongs={dongs} segments={[]} summaries={summary} selected={dong} onSelect={code=>onSelect({dong:code})} nullLabel="자료 없음" missingLabel="자료 없음"/><p>{data.geography.attribution} · 연결 {data.coverage.matched}/{data.coverage.total}</p></article>
     <article className="card"><h3>동별 먼저 확인할 순서</h3><div className="table-scroll"><table><thead><tr><th>순위</th><th>동</th><th>원천 단계</th><th>카드 경보</th><th>최종 단계</th><th>업무</th></tr></thead><tbody>{[...own].sort((a,b)=>a.priority_rank-b.priority_rank).map(r=><tr key={r.dong_cd}><td>{r.priority_rank}</td><th><button aria-pressed={dong===r.dong_cd} onClick={()=>onSelect({dong:r.dong_cd})}>{r.dong_nm}</button></th><td>{r.source_stage_label} ({r.source_stage})</td><td>{alarmText(r)}</td><td>{statusText(r)}</td><td><a href={detailLink(r)}>지역 업무 시작</a></td></tr>)}</tbody></table></div></article></div>
    {selected.filter(r=>r.sex===s).map(row=><article className="card" data-testid={`v4-group-detail-${s}`} key={row.dong_cd}><h3>{row.dong_nm} · {sexName(s)} {row.source_age_band} · {row.frame} 표시 틀</h3><p><strong>원천 단계:</strong> {row.source_stage_label} ({row.source_stage}) · 모집단 {row.population.toLocaleString('ko-KR')} · 약점 {row.weakness_count}개</p><p><strong>카드 경보:</strong> {alarmText(row)} · 연결 원천 연령 {row.card_source_age_bands.join(', ')} · 기준 주 {row.card_week}</p><p><strong>최종 단계:</strong> {statusText(row)} · 조정 {row.stage_adjustment}단계 · 동별 확인 순서 {row.priority_rank}번</p><p>{row.reason}</p><a className="primary-link" href={detailLink(row)}>이 동·원천 연령으로 지역 업무 시작 →</a>
      <details><summary>카드 V/N 원천 신호와 자료 범위</summary><p>자료 버전 {row.dataset_version} · 판정 버전 {data.metadata.methodology_version} · 주간 범위 {data.metadata.weekly_scope}</p><p>원천 연령 {row.source_age_band} · 표시 틀 {row.frame} · 자료 연령 {JSON.stringify(row.source_bands)} · 행정동 원문 {row.source_dong_name}</p><p>기본 단계 {row.base_stage??'산출 안 함'} · 카드 경보 단계 {row.card_alarm_stage??'산출 안 함'} · 카드 기준 주 {row.card_week}</p><div className="table-scroll"><table><thead><tr><th>카드 원천 연령</th><th>기준선</th><th>V 비율·단계</th><th>N 비율·단계</th><th>경보 단계</th></tr></thead><tbody>{row.card_evidence.map(e=><tr key={e.source_age_band}><th>{e.source_age_band}</th><td>{e.baseline_status==='observed'?'관측됨':'기준선 없음'}</td><td>{ratio(e.v_ratio)} · {e.v_stage}</td><td>{ratio(e.n_ratio)} · {e.n_stage}</td><td>{e.alarm_stage}</td></tr>)}</tbody></table></div><p>원천 파일 {data.metadata.source.source} · 카드 파일 {data.metadata.card_source.source} · 입력 해시 {data.metadata.input_hash}</p></details>
     </article>)}
    </section>;})}
   <section className="card" aria-label="카드 주간 근거"><h2>카드 주간 근거 · {week}</h2><p>시군구·성별·원천 연령 단위입니다. 행정동 값으로 해석하지 않습니다. 춘천 60대+ 집단은 60대와 70대+ 카드 원천을 각각 보존합니다.</p><div className="table-scroll"><table><thead><tr><th>성별</th><th>카드 원천 연령</th><th>기준선</th><th>V 비율·단계</th><th>N 비율·단계</th><th>경보</th></tr></thead><tbody>{cards.map(r=><tr key={`${r.sex}-${r.source_age_band}`}><td>{sexName(r.sex)}</td><td>{r.source_age_band}</td><td>{r.baseline_status==='observed'?'관측됨':'기준선 없음'}</td><td>{ratio(r.v_ratio)} · {r.v_stage}</td><td>{ratio(r.n_ratio)} · {r.n_stage}</td><td>{cardStatus(r)}</td></tr>)}</tbody></table></div></section>
  </>}
  <details className="card"><summary>자료 버전·기간·원천</summary><p>데이터셋 {data.metadata.dataset_version} · 입력 스키마 {data.metadata.input_schema_version} · 방법론 {data.metadata.methodology_version} · 카드 기준 주 {data.metadata.selected_week}</p><p>단계 입력 {data.metadata.source.source} ({data.metadata.source.sha256}) · 카드 입력 {data.metadata.card_source.source} ({data.metadata.card_source.sha256}) · 경계 {data.geography.version} · 입력 해시 {data.metadata.input_hash}</p></details>
 </section>;
}
