# beyond-hello-mas

고립을 탐지하고 대응하기 위한 멀티에이전트 시스템. 현재는 FastAPI API와 React 화면의 실행 기반입니다. 결정적 세그먼트 분류와 합성 자원 매칭을 지원하며 승인·위기 우회·재시작 복구를 지원합니다. OpenAI 구조화 출력과 기존 척도 MCP 어댑터가 있으며 실제 OpenAI 검증과 전체 평가는 아직 미완료입니다.

## 로컬 실행

Python 3.12 이상, uv 0.8.8 이상, Node.js 22 이상이 필요합니다.

```sh
make install
cp .env.example .env
make sample
make dev
```

<http://127.0.0.1:5173>에서 관찰(`/observatory`), 담당자 콘솔(`/console`), 평가(`/evaluation`) 화면을 엽니다. API health는 <http://127.0.0.1:8000/health>, OpenAPI는 `/docs`입니다. 종료는 Ctrl-C입니다. 개발 서버는 로컬 인터페이스에서 사용합니다.

기본값은 `DATA_MODE=sample`, `LLM_MODE=fake`이며 키 없이 실행됩니다. sample은 합성 입력이며 실제 고립 판정 결과가 아닙니다. `DATA_MODE=local` 입력은 `data/local/`, 실행 산출물은 `runtime/local/`에 둡니다. sample 실행 산출물도 `runtime/sample/`에 보관합니다. `.env`는 저장소 루트에서 읽습니다.

`LLM_MODE=live`에는 비어 있지 않은 `OPENAI_API_KEY`가 필요합니다. 실제 호출 전에 모델 스냅샷·예산·가격 기준을 설정해야 합니다. 지금은 키 없이 fake로 개발할 수 있으며 [LLM/MCP 사용 안내](docs/llm-usage.md)에 전제와 검증 범위를 구분했습니다.

## 검증

```sh
make test
cd frontend && npx playwright install chromium && cd ..
make e2e
make eval
```

`make test`는 Python 테스트와 TypeScript 검사/빌드를 실행합니다. E2E는 별도 백엔드와 Vite 서버를 띄워 세 화면 이동과 sample/fake health 연결을 확인합니다(8000, 5173 포트가 비어 있어야 합니다).

`make eval`은 계약 검사만 실행하고 JSON으로 `status=incomplete`, 평가 시나리오 수 0, 미구현 항목을 반환합니다. 종료 코드 2는 전체 평가 미완료를 뜻하며 `make`도 실패합니다. fake 검증을 모델 성능으로 보고하지 않습니다.

## 계약과 공개 경계

[데이터 계약](docs/contracts.md)을 참고하세요. Pydantic 모델을 바꾼 뒤 `make contracts`로 프런트엔드용 JSON Schema를 갱신합니다. 평가 정답은 별도 `EvaluationLabel`이며 런타임 `Scenario`에는 포함하지 않습니다.

```sh
uv run python scripts/install_hook.py
uv run python scripts/check_public.py --tracked
```

hook 설치는 기존 hook을 덮어쓰지 않습니다. 기본 검사는 staged Git blob, `--tracked`는 커밋된 HEAD blob 전체를 검사합니다. 로컬 계획·실제 입력·runtime·로컬 평가·환경파일·SQLite 및 부속 파일 경로와 흔한 API 토큰/개인키 패턴을 차단합니다. 임의 경로에 복사한 개인정보·집계나 모든 종류의 비밀값을 탐지하는 검사는 아닙니다. 실제 데이터의 프롬프트·trace·캡처도 공개하지 마세요.

제출은 검사 통과한 커밋에서 `git archive --format=zip --output=../beyond-hello-mas.zip HEAD`로 만듭니다. 작업 폴더 전체를 압축하지 않습니다. 공개 문서는 개인 로컬 계획에 의존하지 않습니다.

## 세그먼트 파이프라인

`make sample && make classify`로 합성 1,692행을 분류합니다. 결과는 `runtime/sample/classification.json`에 저장되며 임시 규칙, 입력 hash, 지표별 공간단위, 누락 정보, 연령별 단계와 동 요약을 포함합니다. 실제 입력 export와 규칙 상세는 [계약 문서](docs/contracts.md)를 참고하세요. 지표 최종 선택과 타당성 검증은 아직 미완료입니다.

실행·트레이스·알림은 `runtime/{DATA_MODE}/events.sqlite3`에 저장합니다. 조회/SSE/수신·확인 API는 `/docs`와 [계약 문서](docs/contracts.md)에 설명되어 있습니다. 수신 ack는 승인이나 실제 기관 전달을 뜻하지 않습니다.


```sh
curl -X POST http://127.0.0.1:8000/scenarios/run -H 'Content-Type: application/json' --data-binary @data/sample/scenario.json
```

응답의 run ID로 `/runs/{id}/approval`을 조회하고 해당 snapshot_version을 `/runs/{id}/decision`에 전달하면 승인/반려할 수 있습니다. 스키마 예시는 `/docs`에 있습니다. 승인 전에는 연계가 없으며, 척도 응답이 없는 사례는 추가 응답을 위한 후속 확인 계획이며, 명시적 응답은 별도로 설정한 MCP로 채점합니다.
