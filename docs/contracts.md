# 데이터 계약 v1

정의: `backend/app/contracts.py`. 전달 형식은 JSON이며 생성된 `frontend/src/contracts.schema.json`을 공유합니다. 모든 객체는 `schema_version="1"`을 가지며 정의되지 않은 최상위 필드를 거부합니다.

- Segment: 2025-07~12 월, 통계청 시군구 5자리/동 7자리 문자열, 동 이름, 연령 구간, 좌표/CRS/출처, 지표/버전, 거주인구, 사각 플래그. `under20/20s/30s/40s/50s/60plus`는 임시 연령 계약입니다. 실제 소스 매핑은 데이터 로더 구현 시 확인합니다. 결측 지표는 null이며 위험 0으로 변환하지 않습니다.
- Scenario: id, monthly/case/crisis/question, sim_time, payload. 시간대 없는 sim_time은 Asia/Seoul로 해석합니다. JSON 출력은 offset을 포함합니다. payload의 중첩 expected도 금지합니다. 평가 전용 EvaluationLabel은 scenario_id와 label_version으로 연결합니다.
- Resource: 관할, 연령 범위, 자격, 욕구, 강도, 전달방식, 신청/발굴 구분, 고립 관련성, URL/수집일/근거, 카탈로그 버전.
- Run: 시나리오/thread 식별자, 상태, 데이터/LLM 모드, 입력·규칙·모델·프롬프트·카탈로그 버전, 시작/종료/오류.
- Trace: run/scenario, 양의 seq, wall/sim 시각, agent/kind, payload, 토큰 수, 지연. kind는 허용된 이벤트 enum만 받습니다. payload 세부 계약은 이벤트 저장 구현에서 추가합니다.
- Approval: snapshot 버전에 묶인 pending/approved/rejected 결정. 완료 결정에는 담당자/시각, 반려에는 사유가 필요합니다.
- Alert: crisis/approval_requested/linkage_completed 유형, 생성/수신/확인 상태와 시각. 수신과 사람 확인은 별도입니다.

wall time은 시간대가 있어야 하며 UTC로 정규화합니다. 월/동/연령의 집합 유일성과 282개×6개월 완전성은 데이터 로더 단계에서 검사할 예정입니다. 현재는 객체 단위 검증이며 통계청 코드의 실제 존재 여부는 확인하지 않습니다. 좌표계를 추측하거나 실제 데이터의 좌표를 공개 sample로 복사하지 않습니다.
