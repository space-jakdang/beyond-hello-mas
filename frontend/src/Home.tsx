export const destinations = [
  {href:'/neighborhoods', title:'동네 분석', eyebrow:'01 · 지역 이해', description:'동네와 집단별 지표, 주간 변화, 결측과 분석 근거를 확인합니다.', action:'분석 대시보드 열기'},
  {href:'/observatory', title:'관찰', eyebrow:'02 · 에이전트 협업', description:'시나리오를 실행하고 분석·검토·추가 조회 과정과 전달 근거를 따라갑니다.', action:'협업 과정 살펴보기'},
  {href:'/policy', title:'정책 탐색', eyebrow:'03 · 지원 자원 조사', description:'중앙정부와 4개 지자체의 정부24 등록 정책을 검색하고 공식 조건을 확인합니다.', action:'지원 정책 찾아보기'},
  {href:'/console', title:'담당자 콘솔', eyebrow:'04 · 사람의 검토', description:'알림과 대응 계획을 검토하고 승인 또는 반려합니다. 실제 외부 전달과는 구분됩니다.', action:'검토할 계획 확인하기'},
  {href:'/evaluation', title:'평가', eyebrow:'05 · 검증과 한계', description:'저장된 계약·합성 시간평가 보고서를 확인합니다. 실제 모델 품질 평가와는 구분합니다.', action:'평가 근거 확인하기'},
];
export function Home() {
  return <>
    <section className="hero">
      <p className="eyebrow">BEYOND HELLO · 지역 기반 고립 대응 연구</p>
      <h2>지역의 신호를 이해하고,<br/>함께 검토할 대응으로 연결합니다.</h2>
      <p>통신·카드 등 지역 집계에서 우선 확인할 동네와 집단을 찾고, 에이전트가 근거를 검토하며 지원 자원을 조사하는 개발 대시보드입니다. 최종 대응은 담당자가 확인합니다.</p>
      <a className="primary-link" href="/neighborhoods">동네 분석부터 시작하기 →</a>
    </section>
    <section aria-labelledby="guide-title"><div className="section-heading"><div><p className="eyebrow">WORKSPACE GUIDE</p><h2 id="guide-title">무엇을 확인하고 싶으신가요?</h2></div><p>처음에는 분석 → 관찰 → 담당자 콘솔 순서로 살펴보세요.</p></div>
      <div className="destination-grid">{destinations.map(item=><article className="destination card" key={item.href}><p className="eyebrow">{item.eyebrow}</p><h3>{item.title}</h3><p>{item.description}</p><a href={item.href}>{item.action} →</a></article>)}</div>
    </section>
    <section className="card scope-note"><h2>화면을 읽기 전에</h2><p><strong>지역 신호는 개인의 고립 판정이 아닙니다.</strong> 개인 판정은 후속 과제로 두고, 현재는 지역 집계의 근거와 대응 계획을 검토합니다.</p><p>상단의 데이터 모드와 LLM 모드를 확인하세요. sample은 합성 입력, fake는 정해진 응답을 사용하는 통신 시연입니다. 정부24 자료 연결 상태는 정책 탐색에서 별도로 확인할 수 있습니다.</p><p>실제 집계에 월 정보가 없는 경우 기간 집계로 표시합니다. 합성 데이터의 예측 결과나 시연 성공을 실제 고립 탐지 정확도로 해석하지 않습니다.</p></section>
  </>;
}
