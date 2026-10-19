import {useState} from 'react';
type Metric={count:number;predicted:number;coverage:number|null;mae:number|null;alert_precision:number|null;alert_recall:number|null};
type Month=Metric&{seed:number;month:string;method:string};
export type Temporal={by_month:Month[];by_pattern:Record<string,Record<string,Metric>>};
export type Paired={paired_results:{month:string;method:string;status:string;violations:string[];calls:number;revisions:number;latency_ms:number;cost_usd:number}[]};
const methodName:Record<string,string>={last_value:'직전 관측 유지',trend:'최근 관측 추세',single:'단일 제안',collaboration:'분석·검토 협업'};
const number=(v:number|null|undefined)=>v==null?'N/A':v.toFixed(3);
const percent=(v:number|null|undefined)=>v==null?'N/A':`${(100*v).toFixed(1)}%`;
export function TemporalPanel({data}:{data:Temporal}){
  const seeds=[...new Set(data.by_month.map(r=>r.seed))];
  const [seed,setSeed]=useState(seeds[0]);
  const rows=data.by_month.filter(r=>r.seed===seed),months=[...new Set(rows.map(r=>r.month))];
  const ymax=Math.max(.01,...rows.map(r=>r.mae??0));
  const x=(i:number)=>45+i*96,y=(v:number)=>155-v/ymax*125;
  return <section className="card" data-testid="temporal-evaluation"><h3>미래 월 예측 · 합성 신호</h3>
    <p>1–6월부터 시작해 7–12월을 한 달씩 예측합니다. 각 월보다 이전의 관측만 사용합니다. 실제 고립 발생 예측은 미평가입니다.</p>
    <label>시험 seed <select value={seed} onChange={e=>setSeed(Number(e.target.value))}>{seeds.map(s=><option key={s}>{s}</option>)}</select></label>
    <p>MAE는 평균 절대 오차이며 작을수록 좋습니다. 예측 불가 건은 coverage에 표시합니다. 파랑: 직전 관측 유지 · 주황: 최근 관측 추세.</p>
    <svg viewBox="0 0 600 200" role="img" aria-label={`seed ${seed} 월별 평균 절대 오차 비교`} style={{width:'100%',maxWidth:800}}>
      <text x="0" y="25">{ymax.toFixed(2)}</text><text x="20" y="158">0</text>
      {(['last_value','trend'] as const).map((method,j)=>{const values=months.map(m=>rows.find(r=>r.month===m&&r.method===method)?.mae);return <g key={method} stroke={j?'#b85c00':'#1476a3'}>{values.map((v,i)=>v==null?null:<g key={i}>{i>0&&values[i-1]!=null&&<line x1={x(i-1)} y1={y(values[i-1]!)} x2={x(i)} y2={y(v)}/>}<circle cx={x(i)} cy={y(v)} r="4"><title>{months[i]} {methodName[method]} MAE {number(v)}</title></circle></g>)}</g>;})}
      {months.map((m,i)=><text key={m} x={x(i)} y="185" textAnchor="middle">{m.slice(5)}월</text>)}
    </svg>
    <div style={{overflowX:'auto'}}><table><thead><tr><th>월</th><th>방식</th><th>MAE ↓</th><th>경보 정밀도</th><th>경보 재현율</th><th>예측 가능 / 전체</th></tr></thead><tbody>{rows.map(r=><tr key={r.month+r.method}><td>{r.month}</td><td>{methodName[r.method]}</td><td>{number(r.mae)}</td><td>{percent(r.alert_precision)}</td><td>{percent(r.alert_recall)}</td><td>{r.predicted} / {r.count} ({percent(r.coverage)})</td></tr>)}</tbody></table></div>
    <p>정밀도: 경보 중 실제 합성 양성 비율. 재현율: 전체 합성 양성 중 경보로 잡은 비율. 미예측 양성도 재현율 분모에 남습니다.</p>
    <details><summary>안정·추세·급변·회복·결측·잡음별 전체 결과</summary><pre>{JSON.stringify(data.by_pattern,null,2)}</pre></details>
  </section>;
}
export function CollaborationPanel({data}:{data:Paired}){
 return <section className="card" data-testid="collaboration-evaluation"><h3>단일 제안과 협업 비교</h3><p>같은 월별 근거와 같은 호출 상한으로 비교합니다. 현재 fake는 통신 계약 검증입니다. 실제 모델의 내용 품질과 협업 효과는 N/A이며, 호출 수 증가만으로 개선을 주장하지 않습니다.</p>
 <div style={{overflowX:'auto'}}><table><thead><tr><th>월</th><th>방식</th><th>계약 검사</th><th>호출</th><th>재작성</th><th>내부 지연</th><th>비용 USD</th></tr></thead><tbody>{data.paired_results.map(r=><tr key={r.month+r.method}><td>{r.month}</td><td>{methodName[r.method]}</td><td>{r.violations.length?r.violations.join(', '):'통과'}</td><td>{r.calls}</td><td>{r.revisions}</td><td>{r.latency_ms.toFixed(1)} ms</td><td>{r.cost_usd.toFixed(6)}</td></tr>)}</tbody></table></div></section>;
}
