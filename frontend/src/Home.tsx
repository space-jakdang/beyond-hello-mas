import {MasFlow} from './MasFlow';
export const primaryPaths=['/neighborhoods','/workspace','/console'];
export const destinations = [
  {href:'/future',title:'미래 시나리오',eyebrow:'자동 분석 시연',description:'지역을 선택하면 합성 미래 3기간을 분석하고, 동별 자원 제안을 확인할 수 있습니다.',action:'미래 시나리오 시작'},
  {href:'/workspace',title:'지역 업무',eyebrow:'에이전트 업무',description:'Supervisor에게 지역 분석을 지시하고, 통계 근거와 자원 제안을 함께 검토합니다.',action:'업무 공간 열기'},
  {href:'/neighborhoods', title:'동네 분석', eyebrow:'지역 이해', description:'동네와 집단별 지표, 주간 변화, 결측과 분석 근거를 확인합니다.', action:'분석 대시보드 열기'},
  {href:'/observatory', title:'관찰', eyebrow:'에이전트 협업', description:'시나리오를 실행하고 분석·검토·추가 조회 과정과 전달 근거를 따라갑니다.', action:'협업 과정 살펴보기'},
  {href:'/policy', title:'정책 탐색', eyebrow:'지원 자원 조사', description:'중앙정부와 4개 지자체의 정부24 등록 정책을 검색하고 공식 조건을 확인합니다.', action:'지원 정책 찾아보기'},
  {href:'/console', title:'담당자 콘솔', eyebrow:'사람의 검토', description:'알림과 대응 계획을 검토하고 승인 또는 반려합니다. 실제 외부 전달과는 구분됩니다.', action:'검토할 계획 확인하기'},
  {href:'/evaluation', title:'평가', eyebrow:'검증과 한계', description:'저장된 계약·합성 시간평가 보고서를 확인합니다. 실제 모델 품질 평가와는 구분합니다.', action:'평가 근거 확인하기'},
];
export function Home() {
  return <>
    <section className="hero">
      <p className="eyebrow">BEYOND HELLO · 지역 기반 고립 대응 연구</p>
      <h2>지역의 신호를 이해하고,<br/>함께 검토할 대응으로 연결합니다.</h2>
      <p>통신·카드 등 지역 집계에서 우선 확인할 동네와 집단을 찾고, 에이전트가 근거를 검토하며 지원 자원을 조사하는 개발 대시보드입니다. 최종 대응은 담당자가 확인합니다.</p>
      <a className="primary-link" href="/workspace">지역 업무 시작하기 →</a> <a href="/neighborhoods">먼저 동네 자료 살펴보기 →</a>
    </section>
    <MasFlow/>
    <section aria-labelledby="guide-title"><div className="section-heading"><div><p className="eyebrow">WORKSPACE GUIDE</p><h2 id="guide-title">무엇을 확인하고 싶으신가요?</h2></div><p>지역 업무에서 시작하고, 제안이 준비되면 담당자 콘솔에서 검토하세요.</p></div>
      <div className="destination-grid">{primaryPaths.map(path=>destinations.find(item=>item.href===path)!).map(item=><article className="destination card" key={item.href}><p className="eyebrow">{item.eyebrow}</p><h3>{item.title}</h3><p>{item.description}</p><a href={item.href}>{item.action} →</a></article>)}</div>
    </section>
    <details className="card"><summary>정책 검색·평가·연구 도구 더 보기</summary><p>현재 자료의 업무와 분리된 조사·검증 도구입니다. 미래 시나리오는 합성 미래를 이용한 실험입니다.</p><ul>{destinations.filter(item=>!primaryPaths.includes(item.href)).map(item=><li key={item.href}><a href={item.href}>{item.title}</a> — {item.description}</li>)}</ul></details>
    <section className="card scope-note"><h2>화면을 읽기 전에</h2><p><strong>지역 신호는 개인의 고립 판정이 아닙니다.</strong> 개인 판정은 후속 과제로 두고, 현재는 지역 집계의 근거와 대응 계획을 검토합니다.</p><p>상단의 자료 준비 상태를 확인하세요. 합성 시연 자료와 정해진 테스트 응답은 실제 관측·모델 판단과 구분됩니다. 정부24 자료 연결 상태는 정책 탐색에서 별도로 확인할 수 있습니다.</p><p>실제 집계에 월 정보가 없는 경우 기간 집계로 표시합니다. 합성 데이터의 예측 결과나 시연 성공을 실제 고립 탐지 정확도로 해석하지 않습니다.</p></section>
  </>;
}
