# 정책 조회 API와 MCP

중앙정부·서울시·강남구·강원도(강원특별자치도)·춘천시의 지원 정책을 정부24 공공서비스 API에서 조회한다. 고립 키워드로 미리 제외하지 않는다. 검색어를 비우면 지정 관할의 전체 등록 목록을 페이지별로 반환한다.

## 조사한 공식 출처

- [행정안전부 대한민국 공공서비스(혜택) 정보](https://www.data.go.kr/data/15113968/openapi.do): 중앙행정기관·지자체 등의 서비스 목록, 상세 내용, 지원 조건. 공공데이터포털 활용 신청과 별도 인증키가 필요하다. 포털의 갱신 주기는 실시간이지만 기관별 공고 등록 시점이나 잔여 예산을 보장하지 않는다.
- [공식 OpenAPI 명세](https://infuser.odcloud.kr/api/stages/44436/api-docs): `https://api.odcloud.kr/api/gov24/v3/`의 `serviceList`, `serviceDetail`, `supportConditions` 사용. 목록은 전체 페이지를 수집하고 소관기관명/유형으로 관할을 구분한다. 상세 조회는 `cond[서비스ID::EQ]` 결과의 ID를 다시 검증한다.

| 범위 | 목록 분류 | 보완 확인할 공식 출처 |
|---|---|---|
| 중앙정부 | 소관기관유형 중앙행정기관/중앙부처 | [정부24](https://www.gov.kr/) |
| 서울시 | 서울특별시/서울시 | [서울 복지](https://news.seoul.go.kr/welfare/) |
| 강남구 | 서울특별시 강남구/서울시 강남구 | [강남 복지](https://bokji.gangnam.go.kr/) |
| 강원도 | 강원도/강원특별자치도 | [강원특별자치도](https://state.gwd.go.kr/) |
| 춘천시 | 강원도 춘천시/강원특별자치도 춘천시 | [춘천애온봄](https://www.chuncheon.go.kr/new-welfare/) |

보완 출처는 조사 링크이며 자동 수집 연결은 아니다. 별도 공공기관 명의 사업, API 미등록 지역 공고가 빠질 수 있다. [한국사회보장정보원 지자체 복지서비스 API](https://www.data.go.kr/data/15108347/openapi.do)도 보완 후보이며 아직 연결하지 않았다. 기존 수기 검수 카탈로그와 이 실시간 조회 결과는 분리한다.

## 설정과 호출

`.env.example`을 참고해 비공개 `.env`에 `GOV24_SERVICE_KEY`를 설정한다. OpenAI 키와 다른 키이며 정부24 해당 데이터의 활용 신청이 필요하다. 인코딩된 키와 디코딩된 키를 모두 받는다. [공식 인증 안내](https://www.data.go.kr/images/biz/swagger-guide/multi_swagger_guide.pdf)에 따라 `Authorization: Infuser …` 헤더로 전송하며 URL에 키를 넣지 않고 리다이렉트를 거부한다. 키가 없어도 서버는 시작되며 `missing_credentials`를 반환한다. 키를 프론트엔드나 MCP 인자에 넣지 않는다.

```sh
uv run python -m backend.policy.server
```

stdio MCP 서버는 `policy_coverage()`, `policy_refresh()`, `policy_search(scopes, query, page, per_page)`, `policy_detail(policy_id)`를 제공한다. MCP 클라이언트는 작업 디렉터리를 저장소 루트로 지정하고 위 명령을 실행한다. 환경변수 `DATA_MODE`, `EVALUATION_ID`로 앱과 동일한 캐시를 선택한다. 외부 MCP 호스트에서도 같은 명령과 환경변수를 사용한다. 서버는 stdout에 일반 로그를 쓰지 않는다.

REST 경로는 `GET /policies/coverage`, `POST /policies/refresh`, `GET /policies?scopes=central&scopes=seoul&query=돌봄&page=1&per_page=20`, `GET /policies/{id}`이다. 앱의 로컬 사용 전제를 따른다. 검색 대상은 제목·요약·지원내용·대상·기관·선정기준이다. 응답은 요청당 10 MB를 넘으면 거부한다. 목록은 캐시 검색이며 갱신은 명시적으로 요청한다. 상세는 요청마다 공식 API를 조회하고 실패하면 캐시/실패 상태를 명시한다.

## 반환값 해석

`coverage`에 각 관할 건수, 수집 시각, 1시간 경과 여부(`stale`), 마지막 갱신 성공/실패, 제외 기관 건수를 반환한다. 미수집 건수는 0이 아닌 null이다. `source_complete`는 해당 수집에서 API 전체 페이지를 읽었다는 뜻이며 `all_policies_known`는 항상 false다. 제공기관의 동시 변경까지 원자적으로 보장하는 API는 아니다.

전체 조회는 기본 최대 30페이지×500건, 약 60초에 개별 요청 timeout을 더한 상한 안에서 실행한다. `POLICY_MAX_PAGES`와 `POLICY_TIMEOUT_SECONDS`로 제한한다. 총건수 변경·중복 ID·중간 실패·상한 초과 시 이전 SQLite 스냅샷을 보존하고 실패를 표시한다. 한도에 걸리면 설정을 조정하고 재시도해야 한다. 반복 요청은 제공기관 쿼터를 소비한다.

정책의 대상·선정기준·지원내용·기한·신청방법·연락처·출처 URL을 반환한다. `supportConditions`는 공식 코드 원문이며 누락/미확인을 적격으로 해석하지 않는다. `eligibility_verified=false`, `remaining_capacity=null`이다. 정책 발견은 신청 가능, 개인 자격 충족, 예산·정원 잔여 확인이나 배정을 뜻하지 않는다. 실제 신청 전 담당기관 확인이 필요하다.

인증키 없는 자동 검증은 공식 명세 기반 합성 응답, 실패 처리, 실제 stdio MCP 통신을 검사한다. 인증된 실 API의 전체 목록·현행성 검증은 키 설정 후 수행해야 한다.


## Supervisor 위임 ReAct 에이전트

관찰 화면의 **Supervisor에게 정책 조사 지시**에서 목표와 관할을 선택한다. 또는 `POST /scenarios/run`에 다음 입력을 전송한다.

```json
{"id":"policy-research","type":"policy","sim_time":"2026-10-18T12:00:00Z","payload":{"goal":"고립 위험 주민에게 도움이 될 지원 정책 조사","scopes":["central","seoul","gangnam","gangwon","chuncheon"],"query":"","max_steps":6}}
```

Supervisor가 위기 신호를 먼저 검사한 뒤 policy worker에 목표/관할을 위임한다. Worker는 매 단계 구조화된 다음 행동을 선택하고 실제 stdio MCP 도구를 호출하며 관측을 다음 모델 입력으로 전달한다. `policy_coverage → refresh → search → detail` 순서를 고정하지 않는다. 모델은 실패·오래된 정보·검색 결과에 따라 다음 행동이나 종료를 선택한다. 도구의 설명과 정책 본문을 실행 지시로 취급하지 않는다.

`LLM_MODE=fake`는 갱신→검색→첫 상세→종료를 사용하는 결정적 통신 시연이며 자율 추론·정책 적합성을 평가한 것이 아니다. `LLM_MODE=live`는 기존 OpenAI 모델/키/가격/예산 설정과 비용 예약·호출 캐시를 사용한다([LLM 설정](llm-usage.md)). 정부24 키와 LLM 키는 별개다. 키 없이도 API/MCP 오류와 종료 흐름을 확인할 수 있다.

상한은 `min(payload.max_steps, LLM_MAX_CALLS)`이며 기본 LLM 호출 한도는 4다. 더 많은 상세/페이지가 필요하면 검증된 비용 예산과 함께 한도를 조정한다(최대 10). 목록 전체는 `/policies`의 페이지 API로 조회할 수 있으며 한 번의 에이전트 실행은 전체 목록을 모두 검토했다고 보장하지 않는다. 전체 도구 관측은 SQLite와 trace에 남기고 모델 입력은 항목당 문자열 800자/목록 5건으로 제한한다. 큰 문맥·비용 초과는 임의로 내용을 만들어 진행하지 않고 종료한다.

결과는 관찰 화면, `GET /runs/{id}/overview`의 `policy`, `policy` 역할의 `node_end` trace에 있다. 실행 완료와 조사 결과 상태는 별개다: `completed`는 상세 근거가 있는 후보를 반환, `no_verified_candidates`는 확인한 후보 없음, `step_limit`/`model_unavailable_or_budget`는 조사 미완료다. `invalid_action`/`invalid_evidence`/`repeated_action`은 안전 종료다. 키 누락 등 원인은 `coverage.last_attempt`와 tool trace에서 확인한다.

추천은 지정 관할 안에서 검색한 ID를 상세 조회한 경우만 허용하며 정책당 추천 한 건과 근거 필드 원문 일치를 검사한다. 전송 중 CRLF/LF 줄바꿈 차이만 동등하게 취급하고 결과에는 제공기관 원문을 보존한다. 설명은 모델의 잠정 관련성 판단이다. API에서 직접 조회했어도 개인 자격·접수·정원을 확정하지 않는다. 예산·단가·정원·수요의 검증된 입력이 없으므로 현재 에이전트는 조사와 후보 추천까지만 하며 실제 자원 배분 최적화·신청·예약·연락은 수행하지 않는다. 기존 사례 승인/연계 흐름을 변경하지 않는다.

도구 결과는 단계마다 저장된다. 재시작은 저장된 관측부터 재개하고 성공한 동일 모델 호출은 비용 장부의 캐시를 재사용한다. 외부 조회 후 로컬 저장 전에 종료된 경우 해당 읽기 도구를 다시 호출할 수 있다. 동일 도구/인자 반복은 중단한다(갱신 후 상태 재확인용 coverage는 단계 상한 내 반복 가능). 공개 서버용 인증/쿼터 관리와 예약 실행은 포함하지 않는다.
