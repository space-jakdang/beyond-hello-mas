# beyond-hello-mas

고립을 탐지하고 대응하기 위한 멀티에이전트 시스템의 로컬 시연 구현입니다. 8집단 지역 분석과 주간 신호, 행정 접수, 개인 판정 MCP 계약, 자원 추천, 승인·반려·복구, 정책 ReAct와 반응형 대시보드를 제공합니다. 기본 시연은 합성 데이터/fake 모델입니다. 실제 개인 판정 MCP v0.2와 사람 적합성 평가는 미완료입니다.

[동네 분석 지도](docs/neighborhoods.md) · [구조](docs/architecture.md) · [고정 평가와 한계](docs/evaluation.md) · [LLM/MCP 설정](docs/llm-usage.md) · [데이터 계약](docs/contracts.md) · [v3 자료 반입](docs/data-policy.md)

## 로컬 실행

Python 3.12 이상, uv 0.8.8 이상, Node.js 22 이상이 필요합니다.

```sh
make install
cp .env.example .env
make sample
make dev
```

<http://127.0.0.1:5173>의 인덱스(`/`)에서 프로젝트 설명과 화면별 이용 순서를 확인합니다. 상단 브랜드나 인덱스 메뉴를 누르면 안내로 돌아갑니다. 동네 분석(`/neighborhoods`), 관찰(`/observatory`), 담당자 콘솔(`/console`), 평가(`/evaluation`), 정책 탐색(`/policy`) 화면을 이용할 수 있습니다. 정책 탐색에서는 서버 인증키 상태, 관할별 수집 건수, 검색·최신 상세 조회와 공식 출처를 확인하고 관찰 화면의 에이전트 조사로 이동합니다. LLM fake/live와 정부24 실제 자료 연결은 별개입니다. API health는 <http://127.0.0.1:8000/health>, OpenAPI는 `/docs`입니다. 종료는 Ctrl-C입니다. 개발 서버는 로컬 인터페이스에서 사용합니다.

기본값은 `DATA_MODE=sample`, `LLM_MODE=fake`이며 키 없이 실행됩니다. sample은 합성 입력이며 실제 고립 판정 결과가 아닙니다. `DATA_MODE=local` 입력은 `data/local/`, 실행 산출물은 `runtime/local/`에 둡니다. sample 실행 산출물도 `runtime/sample/`에 보관합니다. `.env`는 저장소 루트에서 읽습니다.

`LLM_MODE=live`에는 비어 있지 않은 `OPENAI_API_KEY`가 필요합니다. 실제 호출 전에 모델 스냅샷·예산·가격 기준을 설정해야 합니다. 지금은 키 없이 fake로 개발할 수 있으며 [LLM/MCP 사용 안내](docs/llm-usage.md)에 전제와 검증 범위를 구분했습니다.

## 검증

```sh
make test
cd frontend && npx playwright install chromium && cd ..
make e2e
make eval       # 기존 v1 HTTP·브라우저 평가
make eval-v2    # v2 합성 계약 60건 × 2회
```

`make test`는 Python 테스트와 TypeScript 검사/빌드를 실행합니다. E2E는 별도 백엔드와 Vite 서버를 띄워 실행·재연결·승인·반려·월간 조회·평가 JSON 일치를 확인합니다(8000, 5173 포트가 비어 있어야 합니다).

`make eval`은 고정 40건을 별도 서버·DB와 Chromium 수신자로 실행하고 `eval/reports/날짜/UUID/summary.json`에 저장합니다. 명시적 척도 응답 16건에는 별도 MCP 설정이 필요하며, 없으면 실패를 포함한 40건 보고서와 종료 코드 2를 반환합니다. fake 검증은 모델 성능이 아닙니다. [평가 방법과 한계](docs/evaluation.md)를 확인하세요.

## 계약과 공개 경계

[데이터 계약](docs/contracts.md)을 참고하세요. Pydantic 모델을 바꾼 뒤 `make contracts`로 프런트엔드용 JSON Schema를 갱신합니다. 평가 정답은 별도 `EvaluationLabel`이며 런타임 `Scenario`에는 포함하지 않습니다.

```sh
uv run python scripts/install_hook.py
uv run python scripts/check_public.py --tracked
```

hook 설치는 기존 hook을 덮어쓰지 않습니다. 기본 검사는 staged Git blob, `--tracked`는 커밋된 HEAD blob 전체를 검사합니다. 로컬 계획·실제 입력·runtime·로컬 평가·환경파일·SQLite 및 부속 파일 경로와 흔한 API 토큰/개인키 패턴을 차단합니다. 임의 경로에 복사한 개인정보·집계나 모든 종류의 비밀값을 탐지하는 검사는 아닙니다. 실제 데이터의 프롬프트·trace·캡처도 공개하지 마세요.

제출은 검사 통과한 커밋에서 `git archive --format=zip --output=../beyond-hello-mas.zip HEAD`로 만듭니다. 작업 폴더 전체를 압축하지 않습니다. 공개 문서는 개인 로컬 계획에 의존하지 않습니다.

## 세그먼트 파이프라인

`make sample && make classify`로 합성 47동 × 성별 × 4연령 × 6개월, 2,256행을 분류합니다. 실제 전달 집계에 월 정보가 없으면 기간 집계로 유지합니다. 기존 1,692행 분석은 `uv run python -m scripts.classify --legacy`로 남겨 둡니다. 결과는 `runtime/sample/classification.json`에 저장되며 원천별 규칙, 입력 hash, 자료별 연령 범위, 결측 정보, 집단 단계와 동 요약을 포함합니다. 실제 입력 export와 규칙 상세는 [계약 문서](docs/contracts.md)를 참고하세요. 지표 최종 선택과 타당성 검증은 아직 미완료입니다.

실행·트레이스·알림은 `runtime/{DATA_MODE}/events.sqlite3`에 저장합니다. 조회/SSE/수신·확인 API는 `/docs`와 [계약 문서](docs/contracts.md)에 설명되어 있습니다. 수신 ack는 승인이나 실제 기관 전달을 뜻하지 않습니다.


```sh
curl -X POST http://127.0.0.1:8000/scenarios/run -H 'Content-Type: application/json' --data-binary @data/sample/scenario.json
```

응답의 run ID로 `/runs/{id}/approval`을 조회하고 해당 snapshot_version을 `/runs/{id}/decision`에 전달하면 승인/반려할 수 있습니다. 스키마 예시는 `/docs`에 있습니다. 일반 추천은 승인 전 외부 전달이 없으며, 위기·높은 개인 단계는 일반 승인 대기 전에 로컬 담당자에게 인계합니다. 척도 응답이 없는 사례는 추가 응답을 위한 후속 확인 계획이며, 명시적 응답은 별도로 설정한 MCP로 채점합니다.

공식 출처를 확인한 서비스/지점 30건은 [실제 카탈로그 안내](data/catalog/README.md)에 있습니다. `RESOURCE_CATALOG=curated`로 선택할 수 있으며, 개별 자격·접수 가능 여부가 확인된 자원만 추천합니다. 기본 `fixture`는 합성 자원입니다.

## 공개 시연과 제출

![8집단 대시보드](docs/screenshots/groups-v2.png)

[담당자 콘솔 캡처](docs/screenshots/console.png)와 [v2 평가 캡처](docs/screenshots/evaluation-v2.png)는 공개 sample/fake 데이터만 사용했습니다. v2 합성 계약 평가는 60건 2회 재현했습니다. 실제 개인 판정·LLM 응답 추출·독립 적합성 검수는 미완료이며, 고정 위기 표현 테스트를 일반 자연어 탐지 성능으로 해석하지 않습니다. 위기 대응이나 임상 판단의 검증된 시스템으로 사용하지 않습니다.

[제출 재현 기록](docs/release.md)에 고정 코드·보고서·공개 archive 검증을 기록합니다.

정책 실시간 조회 및 MCP 연결: [설정·출처·커버리지](docs/policy-tools.md).

## v2 자료와 해석

**제공 데이터 = 어디·언제(탐지), 외부 = 누구·얼마나(판단)**를 구분합니다. 지역 단계는 먼저 찾아갈 순서이며 개인 진단이 아닙니다. 청년 점수표 AUC **0.825**는 서희 제공 자료(2026-10-18)의 외부 모델 평가 인용이며, 이 MAS의 판정 성능을 측정한 수치가 아닙니다.

서희 32건과 기존 검수 30건은 확인된 동일 사업 3건을 합쳐 로컬 59개 접근 자원으로 구성합니다. 반입 후 `RESOURCE_CATALOG=v3`로 선택합니다. 운영·개인 자격·잔여 정원은 별도 확인 대상입니다. 자세한 반입은 [데이터 정책](docs/data-policy.md), 경계는 [계약](docs/contracts.md)을 참고하세요.

## 지역 협업과 평가 보기

개인 판정 확장은 후순위로 두고 지역 협업·월별 합성 검증을 진행합니다. `/observatory`의 `monthly-collaboration`은 분석안→별도 근거 검토→필요 시 한 번 재작성→담당자 승인 순서입니다. 화면에서 에이전트 간 전달과 수정 요청을 확인할 수 있습니다.

`/evaluation`에서 공개 합성 평가를 기본 조회합니다. `make eval-v2`는 계약, `make eval-temporal`은 시간순 한 달 예측과 기준선, `make eval-collaboration`은 동일 입력의 단일 제안/협업 통신 계약을 평가합니다. 합성 신호 예측을 실제 고립 예측으로, fake 협업 통과를 실제 모델의 품질 개선으로 해석하지 않습니다.
