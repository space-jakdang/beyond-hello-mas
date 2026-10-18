import {useEffect,useState} from 'react';
import {api} from './api';
export type Segment={ym:string;dong_cd:string;age_band:string;stage:number|null;score:number|null;missing:string[];blind_flag:boolean;change_flag:boolean;score_change:number|null;indicators:Record<string,number|null>;components:Record<string,number>};
export type Dong={dong_cd:string;dong_nm:string;sgg:string};
type Geometry={type:'Polygon';coordinates:number[][][]}|{type:'MultiPolygon';coordinates:number[][][][]};
export type Analysis={data_mode:string;months:string[];neighborhoods:Dong[];segments:Segment[];geometry:{features:{properties:Dong;geometry:Geometry}[]};geography:{version:string;crs:string;attribution:string;source_url?:string};coverage:{matched:number;total:number;unmatched_codes:string[]};metadata:{rule_version:string;input_hash:string;normalization:string;staging:string;indicators:{name:string;direction:string;spatial_unit:string}[]}};
export const ages=['10s','20s','30s','40s','50s','60plus'];
export const ageName=(age:string)=>age==='all'?'전체 연령 (최대 단계)':age==='60plus'?'60세 이상':age.replace('s','대');
const colors=['#b8c3c0','#d7e9ed','#96c9cf','#eac767','#df884d','#b84446'];
export function stageOf(rows:Segment[]){const stages=rows.flatMap(r=>r.stage===null?[]:[r.stage]);return stages.length?Math.max(...stages):null;}
const stageName=(stage:number|null)=>stage===null?'결측':`${stage}단계`;

function MapView({data,dongs,segments,selected,onSelect}:{data:Analysis;dongs:Dong[];segments:Segment[];selected:string;onSelect:(id:string)=>void}){
  const [zoom,setZoom]=useState(1);
  const features=data.geometry.features.filter(f=>dongs.some(d=>d.dong_cd===f.properties.dong_cd));
  const polygons=(g:Geometry)=>g.type==='Polygon'?[g.coordinates]:g.coordinates;
  const points=features.flatMap(f=>polygons(f.geometry).flat(2));
  if(!points.length)return <p>연결된 경계가 없습니다. 아래 동 목록에서 결과를 확인하세요.</p>;
  const geographic=data.geography.crs==='EPSG:4326';
  const lat=points.reduce((sum,p)=>sum+p[1],0)/points.length;
  const ratio=geographic?Math.cos(lat*Math.PI/180):1;
  const xs=points.map(p=>p[0]*ratio),ys=points.map(p=>-p[1]);
  const xmin=Math.min(...xs),ymin=Math.min(...ys),width=Math.max(...xs)-xmin,height=Math.max(...ys)-ymin;
  const scale=Math.min(660/(width||1),460/(height||1));
  const project=(p:number[])=>[20+(660-width*scale)/2+(p[0]*ratio-xmin)*scale,20+(460-height*scale)/2+(-p[1]-ymin)*scale];
  return <><div className="toolbar"><button onClick={()=>setZoom(z=>Math.min(4,z+.5))} disabled={zoom===4} aria-label="지도 확대">＋</button><button onClick={()=>setZoom(z=>Math.max(1,z-.5))} disabled={zoom===1} aria-label="지도 축소">−</button><button onClick={()=>setZoom(1)}>전체 보기</button><span>확대 {zoom}× · 확대 후 스크롤로 이동</span></div>
    <div className="map-scroll" tabIndex={0} aria-label="동별 지도 이동 영역"><svg viewBox="0 0 700 500" style={{width:`${zoom*100}%`}} aria-label={geographic?'동별 분석 지도':'합성 동 격자'}>
      {features.map(f=>{const code=f.properties.dong_cd,stage=stageOf(segments.filter(s=>s.dong_cd===code));
        const path=polygons(f.geometry).flatMap(p=>p.map(r=>r.map((v,i)=>`${i?'L':'M'}${project(v).join(',')}`).join(' ')+'Z')).join(' ');
        return <path key={code} d={path} fill={colors[stage??0]} fillRule="evenodd" stroke={selected===code?'#142f36':'#fff'} strokeWidth={selected===code?3:1} vectorEffect="non-scaling-stroke" tabIndex={0} role="button" aria-label={`${f.properties.dong_nm} ${stageName(stage)}`} aria-pressed={selected===code} onClick={()=>onSelect(code)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(code);}}}><title>{f.properties.dong_nm} · {stageName(stage)}</title></path>;
      })}
    </svg></div></>;
}

export function Neighborhoods(){
  const [data,setData]=useState<Analysis>(),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
  const [region,setRegion]=useState('11230'),[month,setMonth]=useState(''),[age,setAge]=useState('all'),[selected,setSelected]=useState('');
  useEffect(()=>{let active=true;setError('');api<Analysis>('/analysis').then(d=>{if(active)setData(d);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[attempt]);
  if(error)return <div role="alert"><p>{error}</p><button onClick={()=>setAttempt(n=>n+1)}>분석 다시 불러오기</button></div>;
  if(!data)return <p>동네 분석을 불러오는 중입니다.</p>;
  const regions=[...new Set(data.neighborhoods.map(d=>d.sgg))].sort();
  const currentRegion=regions.includes(region)?region:regions[0];
  const currentMonth=data.months.includes(month)?month:data.months.at(-1)!;
  const dongs=data.neighborhoods.filter(d=>d.sgg===currentRegion);
  const currentDong=dongs.some(d=>d.dong_cd===selected)?selected:dongs[0]?.dong_cd;
  const segments=data.segments.filter(s=>s.ym===currentMonth&&(age==='all'||s.age_band===age));
  const chosen=dongs.find(d=>d.dong_cd===currentDong);
  return <section className="neighborhoods"><p className="mode-banner">{data.data_mode==='sample'?'합성 데이터 · 격자는 실제 동네 위치가 아닙니다.':'로컬 분석 데이터 · 실제 행정동 경계'} · 임시 단계이며 개인의 고립 진단이 아닙니다.</p>
    <div className="toolbar"><label>지역 <select aria-label="지역" value={currentRegion} onChange={e=>{setRegion(e.target.value);setSelected('');}}>{regions.map(r=><option key={r} value={r}>{r==='11230'?'강남구':r==='32010'?'춘천시':r}{data.data_mode==='sample'?' (합성)':''}</option>)}</select></label><label>분석 월 <select aria-label="분석 월" value={currentMonth} onChange={e=>setMonth(e.target.value)}>{data.months.map(m=><option key={m}>{m}</option>)}</select></label><label>연령 <select aria-label="연령" value={age} onChange={e=>setAge(e.target.value)}>{['all',...ages].map(a=><option key={a} value={a}>{ageName(a)}</option>)}</select></label></div>
    <p>전체 연령은 관측된 연령별 단계의 최댓값입니다. 결측 연령이 있으면 전체 상황을 대표하지 못할 수 있습니다.</p>
    <div className="map-legend" aria-label="단계 범례">{colors.map((color,i)=><span key={color}><i style={{background:color}}/>{i?`${i}단계`:'결측'}</span>)}</div>
    <div className="map-layout"><article className="card"><h2>{currentRegion==='11230'?'강남구':'춘천시'} · {currentMonth}</h2><MapView key={currentRegion} data={data} dongs={dongs} segments={segments} selected={currentDong} onSelect={setSelected}/><p>{data.geography.attribution}</p><small>경계 기준 {data.geography.version} · {data.geography.crs} · 연결 {data.coverage.matched}/{data.coverage.total}</small>{data.coverage.unmatched_codes.length>0&&<p role="alert">경계 미연결 {data.coverage.unmatched_codes.length}곳: 지도에 표시하지 않습니다.</p>}</article>
    <article className="card"><h2>동 선택</h2><p data-testid="selected-neighborhood">{chosen?.dong_nm??'선택 가능한 동 없음'} · {stageName(stageOf(segments.filter(s=>s.dong_cd===currentDong)))}</p><div className="dong-list"><table><thead><tr><th>동네</th><th>단계</th><th>관측 연령</th></tr></thead><tbody>{dongs.map(d=>{const rows=segments.filter(s=>s.dong_cd===d.dong_cd);return <tr key={d.dong_cd} aria-selected={d.dong_cd===currentDong}><th><button aria-pressed={d.dong_cd===currentDong} onClick={()=>setSelected(d.dong_cd)}>{d.dong_nm}</button></th><td>{stageName(stageOf(rows))}</td><td>{rows.filter(r=>r.stage!==null).length}/{age==='all'?6:1}</td></tr>;})}</tbody></table></div></article></div>
  </section>;
}
