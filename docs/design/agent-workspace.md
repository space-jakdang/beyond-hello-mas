# 에이전트 업무 UI

참고: [awesome-design-md Stripe 분석](https://github.com/VoltAgent/awesome-design-md/tree/main/design-md/stripe), [TDS](https://developers-apps-in-toss.toss.im/design/components), [ListRow](https://tossmini-docs.toss.im/tds-mobile/components/ListRow/list-row-overview/), [Badge](https://tossmini-docs.toss.im/tds-mobile/components/badge/).

카탈로그의 밝은 canvas, 짙은 잉크, 얇은 구분선, 숫자 가독성과 TDS의 제목/보조 설명/상태/행동 위계를 참고한다. 제품의 녹색 강조색은 유지하고 중립 배경·넉넉한 여백·목록 중심 작업 화면을 사용한다. 전용 폰트/로고/이미지·TDS 코드/패키지를 복사하지 않는다. 현재 앱은 앱인토스가 아니므로 제한된 자료를 그대로 배포하지 않는다.

지역 업무가 기본 진입점이다. Supervisor·지역 분석·통계 분석·자원 매칭·공무원 검토를 실제 이벤트 상태로 표현한다. 미실행/실행중/완료/보류/실패를 구분한다. 작업 순번과 위험 1~5등급은 별도 텍스트·색으로 구분한다. 결과에는 데이터 모드/방법론/기간/근거 버전이 항상 따라간다.

공통 토큰: ink #191f28, muted #53616d, canvas #f4f6f8, surface #fff, accent #087f72, line #e5e8eb. 8px 간격계, 12~20px 모서리, 16px 본문, 44px 최소 터치 영역. 수치는 tabular-nums. 카드 중첩보다 섹션 제목과 행 구분을 우선한다.

본문 건너뛰기·키보드 포커스·폼 라벨·모바일 재배치 유지. 탭은 버튼과 aria-selected/tabpanel 연결 및 키보드 탐색을 지원한다. 상태는 색만으로 전달하지 않는다. JSON은 개발자용 details로 접고 근거·결론·다음 행동을 먼저 제공한다. PNG는 보조이며 데이터 선택·차트·상세 연동이 본 기능이다.

상태는 항상 한글 라벨과 사유를 제공하고 실행중은 진행 표시, 보류는 확인 필요, 실패는 오류 유형을 함께 표시한다. 상태 변경은 aria-live=polite로 알린다. 탭은 활성 항목만 tabindex=0, 좌우/Home/End 키 이동, aria-controls/aria-labelledby로 연결한다. 실제 검토 상태(반려/보완)는 작업 완료 배지와 별도로 표시한다.
