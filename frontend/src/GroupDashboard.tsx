import {useEffect,useState} from 'react';
import {api} from './api';
import {AllGroups} from './AllGroups';
import {MapView,colors} from './Neighborhoods';
import {Analysis,stageOf} from './neighborhoodData';
type Metric={value:number;baseline:number|null;ratio:number|null;signal:string};
type Weekly={week:string;sgg:string;sex:string;age_band:string;metrics:Record<string,Metric>};
export type Group={ym:string|null;sgg:string;dong_cd:string;dong_nm:string;sex:string;age_group:string;index_name:string;value:number|null;stage:number|null;preferred:boolean;source_bands:Record<string,string[]>;source_period:string;source_file:string;flags:string[];priority_group_applied:boolean;exploratory_replay:boolean;weekly?:Weekly};
export type GroupData=Pick<Analysis,'data_mode'|'months'|'neighborhoods'|'geometry'|'geography'|'coverage'>&{segments:Group[];period_aggregate:boolean;weekly:{rows:Weekly[];weeks:string[]};metadata:{selected_week:string;card_age:string;rule_version:string}};
const names:Record<string,string>={youth:'청년 (19~34)',midlife:'중년 (35~49)',prime:'장년 (50~64)',elderly:'노년 (65+)'};
const stageName=(n:number|null)=>n===null?'미평가':`${n}단계`;

export function GroupDashboard({embedded=false}:{embedded?:boolean}){
  const read=()=>{const result:Record<string,string>={};new URLSearchParams(embedded?'':location.search).forEach((value,key)=>{result[key]=value;});return result;};
  const [selection,setSelection]=useState<Record<string,string>>(read),[data,setData]=useState<GroupData>(),[error,setError]=useState(''),[refresh,setRefresh]=useState(0),[loading,setLoading]=useState(false);
  useEffect(()=>{if(embedded)return;const restore=()=>setSelection(read());window.addEventListener('popstate',restore);return()=>window.removeEventListener('popstate',restore);},[embedded]);
  useEffect(()=>{let active=true;setLoading(true);setError('');const q=new URLSearchParams({card_age:selection.card_age??'all',week:selection.week??'all'});
    api<GroupData>('/analysis/groups?'+q).then(d=>{if(active)setData(d);}).catch(e=>{if(active)setError(String(e));}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};
  },[selection.week,selection.card_age,refresh]);
  if(error)return <div role="alert">{error}<button onClick={()=>{setSelection({});if(!embedded)history.replaceState(null,'','/neighborhoods');setRefresh(n=>n+1);}}>집단 분석 다시 불러오기</button></div>;
  if(!data)return <p>8집단 분석을 불러오는 중입니다.</p>;
  const region=['11230','32010'].includes(selection.region)?selection.region:'11230';
  const sex=selection.sex==='M'?'M':selection.sex==='F'?'F':'all',age=selection.age in names?selection.age:'all';
  const month=data.months.includes(selection.month)?selection.month:(data.months.includes(data.metadata.selected_week.slice(0,7))?data.metadata.selected_week.slice(0,7):data.months.at(-1));
  const dongs=data.neighborhoods.filter(d=>d.sgg===region),dong=dongs.some(d=>d.dong_cd===selection.dong)?selection.dong:dongs[0]?.dong_cd;
  const basis=selection.basis==='seoul'?'seoul':'preferred';
  const groups=data.segments.filter(s=>s.sgg===region&&(sex==='all'||s.sex===sex)&&(age==='all'||s.age_group===age)&&(s.ym===null||s.ym===month));
  const rows=groups.filter(s=>basis==='seoul'&&region==='11230'&&s.age_group!=='youth'?s.index_name==='G_seoul':s.preferred);
  const panels=(sex==='all'?['M','F']:[sex]).map(sex=>{
    const selectedRows=rows.filter(r=>r.sex===sex),series=data.weekly.rows.filter(r=>r.sgg===region&&r.sex===sex&&(data.metadata.card_age==='all'||r.age_band===data.metadata.card_age));
    return {sex,rows:selectedRows,chosen:selectedRows.find(r=>r.dong_cd===dong),series};
  });
  const ratioMax=Math.max(1.2,...panels.flatMap(p=>p.series.flatMap(r=>Object.values(r.metrics).map(m=>m.ratio??0))));
  function choose(patch:Record<string,string>){const next:Record<string,string>={region,sex,age,dong,month:month??'',basis,week:selection.week??data!.metadata.selected_week,card_age:selection.card_age??data!.metadata.card_age,...patch};if(patch.region)next.dong=data!.neighborhoods.find(d=>d.sgg===patch.region)?.dong_cd??'';if(patch.week&&patch.week!=='all')next.month=patch.week.slice(0,7);if(data!.period_aggregate)delete next.month;setSelection(next);if(!embedded)history.pushState(null,'','/neighborhoods?'+new URLSearchParams(next));}
  return <section className="neighborhoods" aria-label="8집단 분석">
    <p className="mode-banner">{data.data_mode==='sample'?'합성 데이터 · 실제 위치가 아닌 격자':'로컬 분석 · 실제 행정동 경계'} · 먼저 찾아갈 순서이며 개인의 고립 진단이 아닙니다.</p>
    <p>지역마다 지표·연령 범위가 달라 강남과 춘천의 수치를 직접 비교할 수 없습니다. {data.period_aggregate?'월 정보 없는 기간 집계입니다. 주간 선택은 과거 신호를 결합한 탐색이며 당시 동별 관측을 뜻하지 않습니다.':data.data_mode==='sample'?'합성 월별 집계':'실제 월별 집계'}</p>
    <div className="toolbar"><label>지역 <select value={region} onChange={e=>choose({region:e.target.value})}><option value="11230">강남구</option><option value="32010">춘천시</option></select></label>
    <label>성별 <select value={sex} onChange={e=>choose({sex:e.target.value})}><option value="M">남성</option><option value="F">여성</option><option value="all">전체 성별</option></select></label>
    <label>연령집단 <select value={age} onChange={e=>choose({age:e.target.value})}><option value="all">전체 연령집단</option>{Object.entries(names).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
    {!data.period_aggregate&&<label>분석 월 <select value={month} onChange={e=>choose({month:e.target.value})}>{data.months.map(m=><option key={m}>{m}</option>)}</select></label>}
    <label>신호 주 <select value={selection.week??data.metadata.selected_week} onChange={e=>choose({week:e.target.value})}><option value="all">전체 관측 주</option>{data.weekly.weeks.map(w=><option key={w}>{w}</option>)}</select></label>
    <label>카드 연령 <select value={selection.card_age??data.metadata.card_age} onChange={e=>choose({card_age:e.target.value})}><option value="all">전체 카드 연령</option><option value="20s">20대</option><option value="30s">30대</option></select></label>
    {region==='11230'&&age!=='youth'&&<label>단계 기준 <select value={basis} onChange={e=>choose({basis:e.target.value})}><option value="preferred">{groups.some(s=>s.index_name==='G_gangnam_rank')?'강남 구내 순위':'제공 기본 기준'}</option><option value="seoul">서울 전체 기준</option></select></label>}
    <button disabled={loading} onClick={()=>setRefresh(n=>n+1)}>{loading?'조회 중':'분석 새로고침'}</button></div>
    {(data.metadata.selected_week==='all'||data.metadata.card_age==='all')&&<p className="mode-banner">전체 관측 신호를 분리해 조회 중 · 기본 등급에 신호 미결합. 분석 월은 지역 지수의 기준이며 신호 주 범위와 별개입니다.</p>}
    <p>주간 신호는 시군구 × 성별 × 20·30대 단위이며 청년 집단에만 적용합니다. 처음 8관측주는 기준선이 없습니다.</p>
    {age==='all'?<AllGroups data={data} rows={rows} dongs={dongs} dong={dong} sex={sex} region={region} month={month??''} onSelect={dong=>choose({dong})}/>:<><div className="map-legend" aria-label="단계 범례">{colors.map((color,i)=><span key={color}><i style={{background:color}}/>{i?`${i}단계`:'미평가'}</span>)}</div>
    {sex==='all'&&<section className="card" aria-label="남녀 동별 단계 비교"><h2>남녀 결과를 각각 확인하세요</h2><p>원천 성별값을 보존합니다. 평균 등급이나 전체 성별 위험을 계산하지 않으며 척도·연령 범위가 다르면 직접 순위를 비교하지 않습니다.</p><div className="dong-list"><table><thead><tr><th>동</th><th>남성 단계·지표</th><th>여성 단계·지표</th></tr></thead><tbody>{dongs.map(d=><tr key={d.dong_cd}><th><button aria-pressed={dong===d.dong_cd} onClick={()=>choose({dong:d.dong_cd})}>{d.dong_nm}</button></th>{panels.map(p=>{const r=p.rows.find(r=>r.dong_cd===d.dong_cd);return <td key={p.sex}>{stageName(r?.stage??null)} · {r?.index_name??'자료 없음'}</td>;})}</tr>)}</tbody></table></div></section>}
    <div className={sex==='all'?'sex-comparison':''}>{panels.map(({sex,rows,chosen,series})=><section key={sex} aria-label={`${sex==='M'?'남성':'여성'} 분석 패널`}>
    <div className="map-layout"><article className="card"><h2>{region==='11230'?'강남구':'춘천시'} · {sex==='M'?'남성':'여성'} · {names[age]}</h2>
      <MapView key={region} data={data} dongs={dongs} segments={rows} selected={dong} onSelect={dong=>choose({dong})}/><p>{data.geography.attribution} · 경계 연결 {data.coverage.matched}/{data.coverage.total}</p>
    </article>{panels.length===1&&<article className="card"><h2>동별 먼저 찾아갈 순서</h2><p data-testid="group-selected">{chosen?.dong_nm??'선택한 집단 자료 없음'} · {stageName(chosen?.stage??null)}</p><div className="dong-list"><table><thead><tr><th>동</th><th>단계</th><th>지표</th></tr></thead><tbody>{dongs.map(d=>{const r=rows.filter(r=>r.dong_cd===d.dong_cd);return <tr key={d.dong_cd}><th><button aria-pressed={dong===d.dong_cd} onClick={()=>choose({dong:d.dong_cd})}>{d.dong_nm}</button></th><td>{stageName(stageOf(r))}</td><td>{r[0]?.index_name??'없음'}</td></tr>;})}</tbody></table></div></article>}</div>
    {chosen?<article className="card" data-testid="group-detail"><h2>{chosen.dong_nm} 원천과 해석</h2><p>{chosen.index_name} · 값 {chosen.value??'결측'} · {stageName(chosen.stage)} · {chosen.source_period}</p>
      <p>이 지표의 자료별 연령: {Object.entries(chosen.source_bands).map(([source,bands])=>`${source}: ${bands.join(', ')}`).join(' / ')}</p>
      <p>주의: {chosen.flags.join(' · ')||'없음'} · 우선집단 +1 {chosen.priority_group_applied?'적용':'미적용'} · 탐색 리플레이 {chosen.exploratory_replay?'예':'아니오'}</p>
      <a className="primary-link" href={'/workspace?'+new URLSearchParams({region,sex,age,dong,month:month??data.metadata.selected_week.slice(0,7)})}>이 동·집단을 Supervisor에게 분석 지시 →</a><p>지도는 주간 신호를 결합한 탐색 결과입니다. 지역 업무는 기본 지수 등급을 별도로 검토하므로 등급이 달라질 수 있습니다.</p>
      <h3>선택한 주의 핵심 근거</h3><p>시군구·성별·카드 연령의 신호입니다. 해당 동만의 실측값은 아닙니다.</p>
      {chosen.weekly?<div className="evidence-cards">{Object.entries(chosen.weekly.metrics).map(([name,m])=><section key={name} aria-label={`${name} 요약`}><h4>{name}</h4><strong>{m.value?.toFixed(3)??'결측'}</strong><dl><dt>직전 8관측주 기준선</dt><dd>{m.baseline?.toFixed(3)??'기준선 없음'}</dd><dt>기준선 대비 비율</dt><dd>{m.ratio===null?'비교 불가':`${m.ratio.toFixed(3)}배`}</dd><dt>변화 신호</dt><dd>{{none:'없음',weak:'약한 신호',strong:'강한 신호'}[m.signal]||m.signal}</dd></dl></section>)}</div>:<p>이 집단에는 주간 신호를 결합하지 않습니다. 위 원천 지수와 자료 범위를 확인하세요.</p>}
      <details><summary>원천 기록 자세히 보기</summary><p>원천 {chosen.source_file} · 규칙 {data.metadata.rule_version}</p><pre>{JSON.stringify(chosen.weekly?.metrics??{},null,2)}</pre></details></article>:<article className="card"><h2>선택한 동의 성별 자료 없음</h2><p>다른 성별의 값으로 채우지 않습니다.</p></article>}
    <article className="card"><h2>주간 신호 리플레이 · {data.metadata.card_age==='all'?'전체 연령 (분리 표시)':data.metadata.card_age==='20s'?'20대':'30대'}</h2><p>각 주를 누르면 지도와 상세가 연결됩니다. 비율은 직전 8관측주 중앙값 대비이며, 점이 없는 구간은 기준선 결측입니다.</p>
      <p>청록색 T1b · 주황색 R1 · 가로선은 기준선 대비 1.0</p>
      <svg viewBox="0 0 700 180" style={{width:'100%'}} role="img" aria-label="T1b R1 주간 비율"><line x1="20" y1={160-140/ratioMax} x2="680" y2={160-140/ratioMax} stroke="#aaa"/>{series.flatMap((r,i)=>['T1b','R1'].map(k=>{const ratio=r.metrics[k].ratio;return ratio===null?null:<circle key={r.week+r.age_band+k} cx={20+i*660/Math.max(1,series.length-1)} cy={160-ratio*140/ratioMax} r={k==='R1'?6:4} fill={k==='R1'?'none':'#25777d'} stroke={k==='R1'?'#b65d2c':'#25777d'} strokeWidth={r.week===data.metadata.selected_week?3:1}><title>{r.week} {k}: {ratio}</title></circle>;}))}</svg>
      <div className="dong-list"><table><thead><tr><th>주</th><th>T1b 비율·경보</th><th>R1 비율·경보</th></tr></thead><tbody>{series.map(r=><tr key={r.week+r.age_band}><th><button aria-pressed={r.week===data.metadata.selected_week} onClick={()=>choose({week:r.week})}>{r.week} · {r.age_band}</button></th>{['T1b','R1'].map(k=><td key={k}>{r.metrics[k].ratio??'기준선 없음'} · {r.metrics[k].signal}</td>)}</tr>)}</tbody></table></div>
    </article></section>)}</div></>}{!embedded&&<a href="/neighborhoods/legacy">과거 6연령 분석 보기</a>}
  </section>;
}
