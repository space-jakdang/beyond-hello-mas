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

`.env.example`을 참고해 비공개 `.env`에 `GOV24_SERVICE_KEY`를 설정한다. OpenAI 키와 다른 키이며 정부24 해당 데이터의 활용 신청이 필요하다. 인코딩된 키와 디코딩된 키를 모두 받는다. 키가 없어도 서버는 시작되며 `missing_credentials`를 반환한다. 키를 프론트엔드나 MCP 인자에 넣지 않는다.

```sh
uv run python -m backend.policy.server
```

stdio MCP 서버는 `policy_coverage()`, `policy_refresh()`, `policy_search(scopes, query, page, per_page)`, `policy_detail(policy_id)`를 제공한다. MCP 클라이언트는 작업 디렉터리를 저장소 루트로 지정하고 위 명령을 실행한다. 환경변수 `DATA_MODE`, `EVALUATION_ID`로 앱과 동일한 캐시를 선택한다. 외부 MCP 호스트에서도 같은 명령과 환경변수를 사용한다. 서버는 stdout에 일반 로그를 쓰지 않는다.

REST 경로는 `GET /policies/coverage`, `POST /policies/refresh`, `GET /policies?scopes=central&scopes=seoul&query=돌봄&page=1&per_page=20`, `GET /policies/{id}`이다. 앱의 로컬 사용 전제를 따른다. 목록은 캐시 검색이며 갱신은 명시적으로 요청한다. 상세는 요청마다 공식 API를 조회하고 실패하면 캐시/실패 상태를 명시한다.

## 반환값 해석

`coverage`에 각 관할 건수, 수집 시각, 1시간 경과 여부(`stale`), 마지막 갱신 성공/실패, 제외 기관 건수를 반환한다. 미수집 건수는 0이 아닌 null이다. `source_complete`는 해당 수집에서 API 전체 페이지를 읽었다는 뜻이며 `all_policies_known`는 항상 false다. 제공기관의 동시 변경까지 원자적으로 보장하는 API는 아니다.

전체 조회는 기본 최대 30페이지×500건, 약 60초에 개별 요청 timeout을 더한 상한 안에서 실행한다. `POLICY_MAX_PAGES`와 `POLICY_TIMEOUT_SECONDS`로 제한한다. 총건수 변경·중복 ID·중간 실패·상한 초과 시 이전 SQLite 스냅샷을 보존하고 실패를 표시한다. 한도에 걸리면 설정을 조정하고 재시도해야 한다. 반복 요청은 제공기관 쿼터를 소비한다.

정책의 대상·선정기준·지원내용·기한·신청방법·연락처·출처 URL을 반환한다. `supportConditions`는 공식 코드 원문이며 누락/미확인을 적격으로 해석하지 않는다. `eligibility_verified=false`, `remaining_capacity=null`이다. 정책 발견은 신청 가능, 개인 자격 충족, 예산·정원 잔여 확인이나 배정을 뜻하지 않는다. 실제 신청 전 담당기관 확인이 필요하다.

인증키 없는 자동 검증은 공식 명세 기반 합성 응답, 실패 처리, 실제 stdio MCP 통신을 검사한다. 인증된 실 API의 전체 목록·현행성 검증은 키 설정 후 수행해야 한다.
