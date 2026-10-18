import {Analysis,Dong,ageName,ages,stageOf} from './neighborhoodData';
const format=(value:number|null|undefined)=>value==null?'N/A':value.toFixed(3);
const names:Record<string,string>={age_share:'연령 유동인구 비중',semester_ratio:'학기 기준 대비 비율',night_share:'야간 유동인구 비중'};
const units:Record<string,string>={dong_age:'동×연령',dong_all_ages:'동 전체 연령',district_age:'시군구×연령'};
type Point={ym:string;stage:number|null;score:number|null};

function Trend({points,metric,month,onMonth}:{points:Point[];metric:'stage'|'score';month:string;onMonth:(month:string)=>void}){
  const values=points.flatMap(p=>p[metric]===null?[]:[p[metric]!]);
  const label=metric==='stage'?'단계':'점수';
  if(!values.length)return <p>{label} 관측값이 없습니다.</p>;
  const min=metric==='stage'?1:Math.min(...values)-.1,max=metric==='stage'?5:Math.max(...values)+.1;
  const x=(i:number)=>55+i*600/Math.max(1,points.length-1),y=(v:number)=>170-(v-min)/(max-min)*140;
  const runs:string[][]=[[]];
  points.forEach((p,i)=>{if(p[metric]===null)runs.push([]);else runs[runs.length-1].push(`${x(i)},${y(p[metric]!)}`);});
  return <svg className="trend-chart" viewBox="0 0 720 220" role="group" aria-label={`월별 ${label} 추이`}>
    {Array.from({length:5},(_,i)=>min+(max-min)*i/4).map(t=><g key={t}><line x1="50" x2="665" y1={y(t)} y2={y(t)} stroke="#d4e3dc"/><text x="44" y={y(t)+4} textAnchor="end">{metric==='stage'?t.toFixed(0):t.toFixed(2)}</text></g>)}
    {runs.filter(r=>r.length>1).map((r,i)=><polyline data-testid={`trend-line-${metric}`} key={i} points={r.join(' ')} fill="none" stroke="#126454" strokeWidth="2"/>)}
    {points.map((p,i)=><g key={p.ym}><text x={x(i)} y="200" textAnchor="middle">{p.ym}</text>{p[metric]!==null&&<circle cx={x(i)} cy={y(p[metric]!)} r={p.ym===month?7:5} fill={p.ym===month?'#b84446':'#126454'} tabIndex={0} role="button" aria-label={`${p.ym} ${label} ${format(p[metric])}`} aria-pressed={p.ym===month} onClick={()=>onMonth(p.ym)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onMonth(p.ym);}}}><title>{p.ym} · {label} {format(p[metric])}</title></circle>}</g>)}
  </svg>;
}

export function NeighborhoodDetails({data,dong,month,age,onAge,onMonth}:{data:Analysis;dong:Dong;month:string;age:string;onAge:(age:string)=>void;onMonth:(month:string)=>void}){
  const rows=data.segments.filter(s=>s.dong_cd===dong.dong_cd);
  const current=rows.filter(s=>s.ym===month);
  const points=data.months.map(ym=>{const group=rows.filter(s=>s.ym===ym&&(age==='all'||s.age_band===age));return {ym,stage:stageOf(group),score:age==='all'?null:group[0]?.score??null};});
  const indicators=data.metadata.indicators;
  return <section aria-label="동네 상세 분석"><article className="card"><h2>{dong.dong_nm} · 연령별 상세</h2><p>{month} · 동 코드 {dong.dong_cd} · 연령을 누르면 지도와 추이를 함께 비교할 수 있습니다.</p>
    <div className="table-scroll"><table aria-label="연령별 분석 결과"><thead><tr><th>연령</th><th>단계</th><th>표준화 점수</th><th>전월 점수 차이</th><th>누락 지표</th><th>추가 확인</th><th>변화 표시</th></tr></thead><tbody>{ages.map(a=>{const s=current.find(s=>s.age_band===a);return <tr key={a} aria-selected={age===a}><th><button onClick={()=>onAge(a)} aria-pressed={age===a}>{ageName(a)}</button></th><td>{s?.stage==null?'결측':`${s.stage}단계`}</td><td>{format(s?.score)}</td><td>{format(s?.score_change)}</td><td>{s?s.missing.map(m=>names[m]??m).join(', ')||'없음':'행 없음'}</td><td>{s?.blind_flag?'필요':s?'—':'N/A'}</td><td>{s?.change_flag?'변화':s?'—':'N/A'}</td></tr>;})}</tbody></table></div>
    <p>추가 확인 표시는 입력 결측·주민 수 확인 등 데이터 점검 필요 상태입니다. 실제 고립 또는 사각지대의 확정 판정이 아닙니다.</p>
    <h3>원지표와 점수 기여도</h3><div className="table-scroll"><table aria-label="원지표와 점수 기여도"><thead><tr><th>연령</th>{indicators.map(i=><th key={i.name}>{names[i.name]??i.name}<small>{units[i.spatial_unit]??i.spatial_unit} · {i.direction==='higher'?'높을수록':'낮을수록'} 점수 증가</small></th>)}</tr></thead><tbody>{ages.map(a=>{const s=current.find(s=>s.age_band===a);return <tr key={a} aria-selected={age===a}><th>{ageName(a)}</th>{indicators.map(i=><td key={i.name}>{format(s?.indicators[i.name])}<small>방향 반영 z값 {format(s?.components[i.name])}</small></td>)}</tr>;})}</tbody></table></div>
    <p>원지표는 비율 단위입니다(0.1 = 10%, 학기 대비 1 = 기준과 동일). 점수는 방향을 반영한 지표별 z값의 평균이며 필수 지표가 빠지면 결측입니다. 야간 비중은 동 전체 연령에 공통인 값으로 연령별 실측값이 아닙니다.</p>
  </article><article className="card"><h2>{dong.dong_nm} · 월별 추이</h2><p>{ageName(age)} · 점을 선택하면 해당 월의 지도·상세로 이동합니다. 결측 구간은 선으로 연결하지 않습니다.</p>
    <h3>단계 추이</h3><Trend points={points} metric="stage" month={month} onMonth={onMonth}/>
    {age!=='all'?<><h3>표준화 점수 추이</h3><Trend points={points} metric="score" month={month} onMonth={onMonth}/></>:<p>전체 연령에는 최대 단계만 표시합니다. 점수 추이는 특정 연령을 선택하세요.</p>}
    <div className="table-scroll"><table aria-label="월별 추이 값"><thead><tr><th>월</th><th>단계</th><th>점수</th><th>관측 연령</th></tr></thead><tbody>{points.map(p=><tr key={p.ym} aria-selected={p.ym===month}><th><button onClick={()=>onMonth(p.ym)} aria-pressed={p.ym===month}>{p.ym}</button></th><td>{p.stage===null?'결측':`${p.stage}단계`}</td><td>{format(p.score)}</td><td>{rows.filter(r=>r.ym===p.ym&&(age==='all'||r.age_band===age)&&r.stage!==null).length}/{age==='all'?6:1}</td></tr>)}</tbody></table></div>
    <p>단계는 각 월의 상대 분위이므로 단계 변화가 절대 위험 증가량은 아닙니다. 표준화는 전체 입력 월을 기준으로 합니다.</p>
  </article><details className="card"><summary>분석 기준과 출처</summary><p>규칙 {data.metadata.rule_version} · 입력 hash <code>{data.metadata.input_hash}</code></p><p>경계 {data.geography.version} · {data.geography.attribution}</p>{data.geography.source_url&&<a href={data.geography.source_url} target="_blank" rel="noreferrer">고정된 경계 원본 보기</a>}<p>2025-07 경계를 모든 분석월에 공통 사용합니다. 이후 행정구역 변경은 별도 검증이 필요합니다. 필터는 기존 분류를 선택할 뿐 재분류하지 않습니다.</p></details></section>;
}
