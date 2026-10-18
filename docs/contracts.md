# 데이터 계약 v1

정의: `backend/app/contracts.py`. 전달 형식은 JSON이며 생성된 `frontend/src/contracts.schema.json`을 공유합니다. Segment와 Resource는 `schema_version="2"`, 나머지 객체는 `schema_version="1"`을 가지며 정의되지 않은 최상위 필드를 거부합니다.

- Segment: 2025-07~12 월, 통계청 시군구 5자리/동 8자리 문자열, 동 이름, 연령 구간, 좌표/CRS/출처, 지표/버전, 거주인구, 사각 플래그. `10s/20s/30s/40s/50s/60plus`는 임시 연령 계약입니다. 실제 소스 매핑은 데이터 로더 구현 시 확인합니다. 결측 지표는 null이며 위험 0으로 변환하지 않습니다.
- Scenario: id, monthly/case/crisis/question, sim_time, payload. 시간대 없는 sim_time은 Asia/Seoul로 해석합니다. JSON 출력은 offset을 포함합니다. payload의 중첩 expected도 금지합니다. 평가 전용 EvaluationLabel은 scenario_id와 label_version으로 연결합니다.
- Resource: 관할, 연령 범위, 자격, 욕구, 강도, 전달방식, 신청/발굴 구분, 고립 관련성, URL/수집일/근거, 카탈로그 버전.
- Run: 시나리오/thread 식별자, 상태, 데이터/LLM 모드, 입력·규칙·모델·프롬프트·카탈로그 버전, 시작/종료/오류.
- Trace: run/scenario, 양의 seq, wall/sim 시각, agent/kind, payload, 토큰 수, 지연. kind는 허용된 이벤트 enum만 받습니다. payload 세부 계약은 이벤트 저장 구현에서 추가합니다.
- Approval: snapshot 버전에 묶인 pending/approved/rejected 결정. 완료 결정에는 담당자/시각, 반려에는 사유가 필요합니다.
- Alert: crisis/approval_requested/linkage_completed 유형, 생성/수신/확인 상태와 시각. 수신과 사람 확인은 별도입니다.

wall time은 시간대가 있어야 하며 UTC로 정규화합니다. 월/동/연령의 집합 유일성과 282개×6개월 완전성은 데이터 로더 단계에서 검사할 예정입니다. 현재는 객체 단위 검증이며 통계청 코드의 실제 존재 여부는 확인하지 않습니다. 좌표계를 추측하거나 실제 데이터의 좌표를 공개 sample로 복사하지 않습니다.

## 세그먼트 분류 v1 (임시)

Segment v2는 원본과 같은 **8자리 통계청 동 코드**를 사용합니다. v1의 7자리 가정은 폐기했습니다. 연령은 SKT의 10대/20대/30대/40대/50대/60대 이상을 `10s/20s/30s/40s/50s/60plus`로 표기합니다. 10대 원자료의 정확한 경계는 공급자 확인 전입니다.

`make sample`은 seed 42로 47개 합성동 × 6연령 × 6개월 = 1,692행 parquet를 생성합니다. 좌표는 합성 격자이고 코드도 합성 식별자입니다. 실제 동의 값·좌표를 복사하지 않습니다. parquet metadata에는 모드, 생성 버전, seed, 행 수, 입력 hash가 포함됩니다.

기본 임시 지표는 연령 유동 비중(낮을수록), 9~11월 대비 유동 비율(낮을수록), 심야 비중(높을수록)입니다. 이는 개발용 신호이며 실제 고립 위험과의 방향·타당성이 검증되지 않았습니다. 3~4개 지표와 방향/허용범위/공간단위를 `Rules` JSON으로 지정할 수 있습니다. 변경 시 version도 올립니다. 실행에는 규칙 hash와 입력 hash가 함께 남습니다.

- 모든 입력 월을 기준으로 모집단 z-score를 계산하고 동일 가중 평균합니다. 기준 입력이 달라지면 점수도 달라질 수 있습니다.
- 월별 유효 점수의 midrank 분위로 5단계를 부여합니다. 동점은 같은 단계, 상수열은 중립인 3단계입니다. 매월 20%씩 강제 배분하지 않습니다.
- 결측·허용범위 밖 지표가 하나라도 있으면 점수/단계는 null입니다. 0분모는 null입니다. 누락 월을 보간하지 않습니다.
- 동 표시 단계는 유효 연령의 최댓값이며, 누락/무효 연령 수를 함께 제공합니다. 바로 전 월이 있는 경우에만 점수 차이와 임시 변화 플래그(절댓값 0.2 이상)를 계산합니다.
- 심야 값은 동 전체 연령을 복제한 값입니다. 카드 지표를 선택할 때도 시군구×연령 자료를 동 실측으로 해석하면 안 됩니다. 현재 카드 값은 기본 지표에서 제외했습니다.

## 로컬 export

```sh
uv run python -m scripts.export_segments /path/to/analysis-project
DATA_MODE=local make classify
```

분석 프로젝트의 SKT age/time CSV, 통계청 2025.10.1 코드 연계표, 월별 주민등록 인구를 읽어 `data/local/segments.parquet`에만 씁니다. 기존 분석 스크립트를 실행하거나 원본을 수정하지 않습니다. 전후 원본 SHA256과 mtime을 비교하고 달라지면 출력을 거부합니다. 실제 소스 이름/해시도 로컬 parquet 안에만 보관합니다.

구 일원2동 `11230740 → 11230511` 매핑을 적용하고, 춘천 면은 코드 순서를 추측하지 않고 연계표를 조회합니다. 정확히 중복된 행(12월 time/wkdy 알려진 문제)은 제거하고, 블록/좌표/월이 같은 충돌 행은 거부합니다. 현재 wkdy는 미사용입니다. 카드 법인은 AGE_CCD/SEX_CCD로 제외해야 하나 현재 export에서 카드는 미사용입니다.

좌표는 정의서 UTM-K 및 기존 분석의 EPSG:5179를 따라 원좌표 평균을 보존합니다. 위경도 변환은 하지 않습니다. 거주인구 누락은 null로 남기고 사각 플래그를 켭니다. local 파일이 없으면 실패하며 sample로 대체하지 않습니다. 단계는 지역·시점의 상대적 개발 지표이며 개인 진단이나 실제 고립 탐지 정확도가 아닙니다.

## 카탈로그와 결정적 매칭

Resource v2는 `eligibility_tags`, `active`, 만료일 포함 `valid_until`을 추가합니다. CSV 열 이름은 Resource 필드와 같고 `jurisdiction/needs/eligibility_tags`는 JSON 배열입니다. ID는 유일하고 catalog_version은 전체에 동일해야 합니다. `data/sample/resources.csv`는 합성 개발 fixture이며 example.invalid URL은 실제 서비스가 아닙니다.

지원 관할은 전국 `KR`, 서울 `11`/강남 `11230`, 강원 `32`/춘천 `32010`입니다. 요청 관할의 기초·광역·전국 자원을 허용합니다. 자원 연령 범위는 요청 연령 범위 전체를 포함해야 합니다. 개인은 최솟값=최댓값, 집단은 연령대 전체를 전달합니다. 자격 태그가 명시적으로 true가 아니면 제외합니다. 태그 없는 자원은 eligibility가 `unrestricted`인 경우만 허용하며 자유문장 자격을 충족했다고 추정하지 않습니다.

`backend/tools/matching.py`는 활성/만료·수집일·관할·연령·자격·욕구·개입 강도를 필터합니다. `as_of`는 카탈로그 유효성 확인 날짜이며 시뮬레이션 시간과 별도입니다. 일치 욕구 수 내림차순, 자원 ID 오름차순으로 최대 3개를 반환합니다. 원래 근거 필드, 제외 이유, 미충족 욕구, 부족 수, 입력/카탈로그/정책 hash를 함께 반환합니다. LLM 설명에는 이 확정 후보만 전달합니다.

임시 `provisional-1` 정책은 단계 1~2=low, 3=medium, 4~5=high로 매핑합니다. `map_needs`는 명시적 원인 라벨만 사용하며 미상 원인은 빈 목록입니다. 임상적 위험 환산이 아니며 `MatchPolicy`로 수정할 때 버전과 hash를 기록합니다. 단계가 없으면 낮은 강도로 임의 매핑하지 않습니다.

CLI: `uv run python -m scripts.match request.json --catalog data/sample/resources.csv`. 출력에는 비공개 입력이 반영될 수 있으므로 local 파생 결과는 `runtime/local/`에만 보관합니다. 추천은 실제 외부 전달이 아닙니다.

## 영속 이벤트와 SSE

단일 로컬 서버가 `runtime/{sample|local}/events.sqlite3`에 run/trace/alert/클라이언트 수신을 저장합니다. 쓰기는 SQLite `BEGIN IMMEDIATE` 트랜잭션, 외래키 및 유일성 제약을 사용합니다. 알림과 감사 trace는 함께 커밋되거나 함께 롤백됩니다. run의 data_mode가 저장소와 다르면 거부합니다. 다중 서버/사용자 인증을 제공하는 배포 서비스는 아닙니다.

- `GET /runs` 및 `/runs/{id}`: 조회. 실행 생성은 `/scenarios/run`에서만 합니다.
- 알림 생성은 그래프 내부에서만 합니다. `GET /alerts`: cursor 순 조회. 공개 API로 승인/연계 완료 알림을 임의 생성할 수 없습니다.
- `GET /runs/{id}/traces`: run별 seq 순 조회. 조회는 after/limit으로 페이지를 나눕니다.
- `GET /runs/{id}/traces/stream`, `GET /alerts/stream`: SSE. `Last-Event-ID` 또는 after 이후 이벤트를 최대 100개씩 DB에서 재조회하며 15초 heartbeat를 전송합니다. 알림 cursor는 모든 run에 걸쳐 증가합니다. 느린 구독자용 무제한 메모리 큐를 만들지 않으며 연결 종료 시 generator가 취소됩니다.
- `POST /alerts/{id}/receipt`: client_id, browser_received_at, sim_ts. client_id는 브라우저별 안정적인 ID이며 같은 알림/클라이언트의 최초 기록을 보존합니다. 브라우저 시계 원시값과 UTC 서버 수신 시각은 분리합니다.
- `POST /alerts/{id}/acknowledge`: client_id, operator, sim_ts. 그 클라이언트의 수신 기록이 있어야 합니다. 사람의 확인은 승인 결정과 별개이며 최초 확인과 감사 trace만 기록합니다.

run 등록부터 서버 receipt까지는 같은 프로세스의 단조 시계로 `run_to_receipt_ms`를 계산합니다. 재시작 후 시계 원점이 달라진 실행은 null로 남깁니다. 브라우저 시각을 빼서 시스템 지연을 계산하지 않으며 미수신·재시작 결측을 0으로 보고하지 않습니다. 시뮬레이션 시각은 성능 지연에 쓰지 않습니다. 실제 브라우저 수신 지연 평가는 후속 단계입니다.

SQLite 연결/트랜잭션 의미는 [Python 공식 문서](https://docs.python.org/3/library/sqlite3.html)를 따릅니다.


## 그래프와 승인

`POST /scenarios/run`에 Scenario를 전달합니다. FastAPI의 작업 스레드에서 그래프를 실행하며 health/SSE 이벤트 루프를 막지 않습니다. `GET /runs/{id}/approval`은 승인 대상 전체 proposal과 snapshot hash를 반환합니다. `POST /runs/{id}/decision`은 snapshot_version, approved/rejected, operator, 반려 시 reason을 받습니다. `GET /runs/{id}/linkage`는 승인 후의 로컬 연계 기록입니다.

일반 경로는 supervisor → classify → match → approval → link입니다. 승인 노드의 `interrupt` 체크포인트가 저장된 뒤에만 승인 요청과 알림을 한 트랜잭션으로 공개합니다. 결정은 해당 snapshot에 결박하고, 같은 run의 재개를 직렬화합니다. 결정 저장 후 프로세스가 종료되어도 시작 시 재개합니다. 연계/알림/후속 확인 일정은 run별 한 번만 생성됩니다. 반려는 종료하며 연계하지 않습니다. 체크포인트가 없거나 snapshot이 다르면 승인을 거부합니다.

위기는 payload 안의 모든 문자열을 먼저 규칙으로 검사합니다. 시나리오 type이나 평가 정답은 위기 판정에 사용하지 않습니다. 위기 경로는 supervisor → link이며 분류/매칭/LLM/일반 승인을 우회합니다. 규칙 provisional-1은 일부 명시적 한국어 신호와 제한된 부정문만 다루며 포괄적 위기 탐지 성능을 보장하지 않습니다. 알림은 로컬 담당자용이며 기관에 실제 전달하지 않습니다.

monthly는 해당 월의 연령별 배분안 전체를 하나의 승인 단위로 둡니다. 개인 사례에 명시적 척도 응답이 없으면 assessment_pending으로 유지하고 점수·단계를 만들지 않습니다. 이때 승인 대상은 추가 응답/상담을 위한 후속 확인 계획이며 자원 추천은 비어 있습니다. 명시적 응답은 MCP로 채점하며 외로움/사회적 고립 결과를 분리합니다. 질문은 제한된 라우팅 enum으로 한 번만 실행하고 link 요청에도 승인 게이트를 적용합니다. live 설정/호출 실패를 fake 성공으로 바꾸지 않습니다.

fake 모드의 초안은 fake로 표시하며 어떤 모드에서도 외부 전달은 없습니다. 일반 후속 확인 일정은 개발용 기본 7일 후입니다. 그래프 checkpoint는 모드별 `runtime`에 저장하고 외부 LangSmith tracing은 호출 컨텍스트에서 비활성화합니다. 재시작 복구는 실행별로 수행하며 실패한 실행도 error trace에 남습니다. 지원 범위는 단일 백엔드 프로세스입니다.

구현은 LangGraph 공식 [interrupt](https://reference.langchain.com/python/langgraph/types/interrupt)와 [SqliteSaver](https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver) 계약 및 고정된 설치 버전을 사용합니다.
