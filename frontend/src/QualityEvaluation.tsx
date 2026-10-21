import {useEffect,useState} from 'react';
import {api} from './api';
import {MatchingQuality,MatchingData} from './MatchingQuality';
import {ClassificationQuality,ClassificationData,percent} from './ClassificationQuality';
type Ready={cases:number;reference_items:number;missing:number;unknown:number;disagreement:number;resolved:number;independent_resolved:number};
type Brief={id:string;dataset:string;version:string;status:string;readiness:Ready|null};
type Reference={policy_id:string|null;state:string;independent:boolean;review_count:number;adjudicated:boolean;provenance:string[]};
type Detail=Brief&{matching?:MatchingData|null;classification?:ClassificationData|null;dataset_hash:string;label_hash:string;filters:Record<'region'|'period'|'methodology'|'source',string[]>;cases:{id:string;region:string;neighborhood:string;period:string;methodology:string;source:string;references:Reference[]}[];limitations:string[]};
const states:Record<string,string>={missing:'미등록',unknown:'판단불가',disagreement:'이견 조정 필요',resolved:'참조 등록'};
const axes=[['분류 품질','독립 등급 기준답과 예측 결과가 필요합니다.'],['자원 매칭','정책별 적합성 평정과 추천 결과가 필요합니다.'],['설명 근거','실제 모델 입력·응답과 근거 평가가 필요합니다.'],['지역·시간 일반화','미사용 실제 지역·후속 기간 평가가 필요합니다.'],['MAS 효과','같은 조건의 규칙·단일·다중 에이전트 비교가 필요합니다.']];
export function QualityEvaluation({source,reload}:{source:string;reload:number}){
 const [rows,setRows]=useState<Brief[]>([]),[selected,setSelected]=useState(''),[detail,setDetail]=useState<Detail>(),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 const [options,setOptions]=useState<Detail['filters']>();
 const [region,setRegion]=useState(''),[period,setPeriod]=useState(''),[methodology,setMethodology]=useState('');
 useEffect(()=>{let active=true;setRows([]);setDetail(undefined);setError('');setLoading(true);
 api<Brief[]>(`/reports/quality?source=${source}`).then(data=>{if(active){setRows(data);if(!data.some(r=>r.id===selected)){setSelected(data[0]?.id||'');setOptions(undefined);setRegion('');setPeriod('');setMethodology('');}setLoading(false);}}).catch(e=>{if(active){setError(String(e));setLoading(false);}});return()=>{active=false;};},[source,reload]);
 useEffect(()=>{let active=true;setDetail(undefined);setError('');if(!selected)return;
 const query=new URLSearchParams({source,...(region?{region}:{}),...(period?{period}:{}),...(methodology?{methodology}:{})});
 api<Detail>(`/reports/quality/${selected}?${query}`).then(data=>{if(active){setDetail(data);setOptions(data.filters);}}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[selected,source,region,period,methodology,reload]);
 const reset=(id:string)=>{setDetail(undefined);setOptions(undefined);setSelected(id);setRegion('');setPeriod('');setMethodology('');};
 return <section aria-label="분석 품질 평가" data-testid="quality-evaluation"><h2>분석 품질 평가</h2><p>얼마나 잘 분류하고 적절한 자원을 추천했는지 확인합니다. 실행 성공률과 품질 점수는 별개입니다.</p>
 <div className="evidence-cards">{axes.map(([name,why])=><section key={name}><h3>{name}</h3><strong>{name==='분류 품질'&&detail?.classification?.groups.length===1?percent(detail.classification.groups[0].macro_f1):name==='분류 품질'&&detail?.classification?'범위별 결과':name==='자원 매칭'&&detail?.matching?'사례별 결과':'미평가'}</strong><p>{name==='분류 품질'&&detail?.classification?'Macro-F1 · 독립 참조 기준 · 실제/합성 및 방법론별 분리':why}</p></section>)}</div>
 {error&&<p role="alert">평가 자료를 읽지 못했습니다. {error}</p>}
 {loading?<p role="status">평가 자료를 불러오는 중입니다.</p>:!rows.length&&!error?<p>등록된 평가 자료가 없습니다. 기준답을 등록하면 준비 현황을 확인할 수 있습니다.</p>:null}
 {!!rows.length&&<label>품질 평가 자료 <select value={selected} onChange={e=>reset(e.target.value)} style={{maxWidth:'100%'}}>{rows.map(r=><option key={r.id} value={r.id}>{r.dataset} · {r.version} · {r.status==='failed'?'자료 오류':r.status==='partial'?'부분 평가':'평가 준비'} · {r.id.slice(0,8)}</option>)}</select></label>}
 {options&&<div className="filters">{([['region','지역',region,setRegion],['period','기간',period,setPeriod],['methodology','방법론',methodology,setMethodology]] as const).map(([key,label,value,setter])=><label key={key}>{label} <select value={value} onChange={e=>{setDetail(undefined);setter(e.target.value);}}><option value="">전체</option>{options[key].map(v=><option key={v} value={v}>{v}</option>)}</select></label>)}</div>}
 {detail&&<><p>{source==='sample'?'공개 합성 입력':'현재 서버 입력'} · {detail.classification?'분류 예측 가져옴 · 근거 평가는 별도':'모델 평가 미실행 · 점수 없음'}</p>
 <section aria-label="기준답 준비 현황" className="evidence-cards">{[['입력 사례',detail.readiness?.cases],['평정 대상',detail.readiness?.reference_items],['독립 참조 등록',detail.readiness?.independent_resolved],['미등록',detail.readiness?.missing],['판단불가',detail.readiness?.unknown],['미해결 이견',detail.readiness?.disagreement]].map(([label,value])=><section key={label}><h3>{label}</h3><strong>{value}</strong></section>)}</section>
 <p>독립 참조 수는 사례·정책별 항목 수입니다. 입력 사례 수나 정확도가 아닙니다.</p>
 {!detail.cases.length&&<p>선택한 조건에 해당하는 사례가 없습니다.</p>}
 {detail.classification&&<ClassificationQuality data={detail.classification}/>}
 {detail.matching&&<MatchingQuality data={detail.matching}/>}
 <h3>사례별 평가 준비</h3>{detail.cases.map(c=><details key={c.id} className="card"><summary>{c.neighborhood} · {c.period} · {c.source==='synthetic'?'합성':'실제 관측'} · {c.references.filter(r=>r.state==='missing').length}개 미등록</summary><p>{c.region} · {c.methodology}</p><ul>{c.references.map(r=><li key={r.policy_id||'grade'}>{r.policy_id?`정책 ${r.policy_id}`:'지역 등급'}: {states[r.state]||r.state} · 검토 {r.review_count}명 · {r.independent?'독립 참조':'독립 참조 미충족'}{r.adjudicated?' · 조정 완료':''}</li>)}</ul><p>추천 이유와 원문 연결은 결정 근거 기록 후 제공됩니다.</p></details>)}
 <ul>{detail.limitations.map(v=><li key={v}>{v}</li>)}</ul><details><summary>평가 입력·기준답 버전</summary><p style={{overflowWrap:'anywhere'}}>입력 {detail.dataset_hash}<br/>기준답 {detail.label_hash}</p></details></>}
 </section>;
}
