# Vercel deployment

The repository root is a FastAPI application. Vercel builds the Vite frontend through the `tool.vercel.scripts.build` command in `pyproject.toml`; FastAPI serves the resulting frontend and API from one origin. Keep API credentials in Vercel server-side Environment Variables. Never prefix them with `VITE_`.

In the Vercel project setup, use:

| Setting | Value |
|---|---|
| Root Directory | `./` |
| Framework Preset | `FastAPI` |
| Build Command | Leave blank (the repository build script runs) |
| Output Directory | Leave blank (FastAPI serves `frontend/dist`) |
| Install Command | Leave blank (Vercel detects Python dependencies) |

Production uses the existing regional input package. Set `RUNTIME_INPUT_PACKAGE` as described below before deploying. A Production deployment without a valid confirmed package fails at startup, even if an old `DATA_MODE=sample` setting remains. Sample mode is available only for Preview/development through this entrypoint.

Set these server-side Environment Variables for a synthetic Preview:

| Name | Value |
|---|---|
| `DATA_MODE` | `sample` |
| `LLM_MODE` | `live` |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `OPENAI_MODEL` | A model enabled for your API project, such as `gpt-5.6-terra` |
| `INPUT_USD_PER_MILLION` | Current model input price; for `gpt-5.6-terra`, `2` |
| `OUTPUT_USD_PER_MILLION` | Current model output price; for `gpt-5.6-terra`, `12` |
| `PRICE_VERSION` | A label recording when you checked the prices, e.g. `2026-10-23` |
| `LLM_BUDGET_USD` | A nonzero total budget, e.g. `2` |
| `LLM_RUN_BUDGET_USD` | Optional per-run cap, e.g. `0.35` |
| `LLM_MAX_CALLS` | `10` for the full regional analysis → statistics → policy workflow |
| `POLICY_DESIGN_MAX_OUTPUT_TOKENS` | `8192` for three detailed policy alternatives |
| `GOV24_API_KEY` | Your data.go.kr 대한민국 공공서비스(혜택) 정보 service key |
| `PERSON_MCP_MODE` | `stub` |

The key values must be entered in Vercel’s server environment settings, not in Build Environment Variables or frontend settings. `OPENAI_API_KEY` and `GOV24_API_KEY` are read only by the Python runtime. Vercel creates a new deployment after environment variables change.

The model and prices above are an example, and must match the model actually selected in your OpenAI project. OpenAI currently lists GPT-5.6 Terra at $2 per million input tokens and $12 per million output tokens; check the [current model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra) before changing these values. This application requires model pricing and a nonzero budget to enable live calls.

## 기존 지역 자료를 배포 기본값으로 연결

Git에서 제외된 `data/local`은 Git 연동 배포에 포함되지 않습니다. `DATA_MODE=local`만 지정해도 기존 파일이 서버로 전송되지는 않습니다. 접근 제한을 적용한 비공개 심사 배포에는 [최소 입력 패키지](runtime-inputs.md)를 서버 전용 환경변수로 연결합니다. MDIS·복지패널 개인 원자료, 로컬 DB, 기존 실행 결과는 포함하지 않습니다.

1. 반입 범위가 확인된 패키지를 준비합니다. manifest의 `permission_status=private_contest_use_confirmed`가 필요합니다. `pending`을 임의로 바꾸지 마세요. 이 확인은 실제 공개 배포 허가를 의미하지 않으므로 UI·API·다운로드 모두 배포 접근 보호를 먼저 적용합니다.
2. 비공개 경로에서 값을 생성합니다. 기존 파일 덮어쓰기는 거부하며 출력 파일 권한은 `0600`입니다. 값 자체를 터미널·로그·PR에 출력하지 않습니다.

   ```sh
   uv run python -m scripts.runtime_package encode /private/releases/input-v1 --output /private/runtime-input-package.txt
   ```

3. 이 파일의 내용 전체를 Vercel 프로젝트의 서버 전용 `RUNTIME_INPUT_PACKAGE` 환경변수로 등록하고 사용할 Production/Preview 환경에 적용합니다. `VITE_` 접두사를 붙이지 않습니다. 서버만 읽는 값이며 Git·정적 폴더·공개 CI artifact에 넣지 않습니다. 압축과 Base64는 암호화가 아닙니다.
4. 이후 새 배포와 새 함수 인스턴스는 같은 패키지에서 입력을 복원하고 `local`/`v3`를 선택합니다. 패키지 v1은 `regional-workflow-1`, v2는 `regional-workflow-2`를 선택합니다. 이전 `DATA_MODE=sample`, `RESOURCE_CATALOG=fixture`, `INPUT_ROOT`보다 이 패키지가 우선합니다. 누락·변조·잘못된 출처/경계·미확인 반입은 합성 자료로 대체하지 않고 시작을 실패시킵니다.
5. 인증된 `/readiness`에서 `data_mode=local`, `analysis.geometry=administrative_boundaries`, `catalog.version=v3`, `ready=true`를 확인하고 실제 동 이름을 점검합니다. 코드의 기존 `create_app` 개발/시험 factory는 환경 패키지를 자동 반입하지 않습니다. Vercel은 루트 `app.py`를 진입점으로 사용해야 합니다.

현재 전송 방식은 인코딩 후 48 KiB, 압축 해제 후 8 MiB 이하의 작은 고정 입력용입니다. [Vercel 환경변수 제한](https://vercel.com/docs/environment-variables#environment-variable-size)은 Python 배포의 모든 환경변수를 합쳐 64 KB이므로 키 등 다른 값도 합산해야 합니다. 입력이 커지면 비공개 객체 저장소나 [상주 서버](private-service.md)를 사용합니다. 환경변수 변경은 새 배포부터 적용됩니다.

이 설정은 기본 관측 입력을 보존합니다. 새로 생성한 실행 이력·승인·정책 캐시는 아래 `/tmp` 제한을 그대로 따릅니다. 영속 실행 이력이 필요한 서비스에는 상주 서버 구성을 사용합니다.

## Runtime limit

Vercel Functions have a read-only filesystem except for temporary `/tmp` storage. This deployment redirects runtime files there so the app can start and make real API calls. `/tmp` is not durable and is not shared reliably between function instances. Runs, approvals, checkpoints, cached Gov24 data, and quality-job artifacts can disappear or be unavailable on a later request or cold start. FastAPI background tasks are also not a durable job queue. Use this only as a live Preview/demo; persistent workflows require a shared PostgreSQL store and durable worker/queue before public production use.

## 실제 동과 지도 / 실행 이력 누락 진단

`DATA_MODE=sample`은 의도적으로 합성동과 격자를 표시합니다. OpenAI·정부24 키를 넣어도 지역 집계가 실제 데이터로 바뀌지는 않습니다. `GET /readiness`에서 `data_mode`, `analysis.geometry`, 경계 연결 수, 자료 준비 여부와 저장 방식부터 확인하세요. 준비되지 않은 실제 자료를 합성 자료로 자동 대체하지 않습니다.

실제 지역 분석 서버에는 다음 설정과 파일이 필요합니다.

- `DATA_MODE=local`, `RESOURCE_CATALOG=v3`
- `INPUT_ROOT=/secure/inputs`: 이 경로 아래 `local/segments-v3.parquet`, `local/resources-v3.csv`, `local/seohee/`의 반입 manifest와 주간 신호 원천을 배치합니다. 기존 반입/해시 검증을 그대로 통과해야 합니다. 과거 6연령 화면은 별도 `local/segments.parquet`도 필요합니다.
- 실제 행정동 경계와 출처는 저장소의 `data/geography/`를 사용합니다. 집계의 동 코드·이름과 일치하지 않는 경계는 연결하지 않습니다.
- `RUNTIME_STORAGE_ROOT=/persistent/state`: 재시작에도 유지되는 서버 볼륨을 연결합니다. 이벤트·정책 캐시·체크포인트의 기존 경로 계산을 함께 이동합니다. 경로 지정 자체가 볼륨 영속성을 보장하지 않습니다. 단일 상주 서버/단일 worker로 운영하고 백업 및 재시작 후 기존 run 조회를 확인하세요.

현재 Vercel 함수의 `/tmp`는 위 영속 볼륨이 아닙니다. `RUNTIME_INPUT_PACKAGE`는 고정 관측 입력을 복원하지만 실행 이력을 영속화하지 않습니다. 자료와 영속 볼륨을 가진 단일 상주 FastAPI 서버에서 빌드된 UI와 API를 함께 제공하는 것이 최소 영속 운영 구성입니다. Vercel에 계속 전체 API를 배치하며 실행 이력까지 보존하려면 공유 DB·객체 저장소·지속 실행 worker 이전이 필요합니다.

실제 집계는 Git 제외 대상이며 `rules/source_permissions.json`에 공개 확인 전인 원천이 포함되어 있습니다. `data/local`을 저장소나 공개 번들에 복사하지 마세요. 사용 권한이 확인된 접근 제한 서버에 별도로 반입합니다. `/readiness`는 파일 경로·키·원천 레코드를 반환하지 않습니다. 403은 배포 접근 보호·플랫폼 정책 또는 외부 API 권한 응답인지 요청 URL/응답에서 구별해야 하며, 기존 지도·집단 분석 API의 집계 자료 누락은 503으로 반환합니다. 지역 통계 진단인 `/analysis/regional-context`는 키나 외부 자료가 없으면 HTTP 200과 `partial`/`unavailable` 상태를 반환합니다. `/readiness`는 진단 보고서를 항상 200으로 반환하므로 준비 여부는 본문의 `ready`를 확인합니다.

UI 상단의 자료 준비 상태에서 합성/실제 자료 설정, 경계 연결, 임시 저장 경고를 확인할 수 있습니다. 일상 업무 메뉴는 동네 분석→지역 업무→담당자 콘솔이며 정책 탐색·평가·관찰·합성 미래 실험은 검증·연구 도구에 모았습니다. 이 표시는 API 키의 실제 유효성이나 저장 볼륨 영속성 검증을 대신하지 않습니다.

세 정책안이 기본 구상안으로만 나오는 경우 정책 검색뿐 아니라 호출 예산도 확인하세요. 기본 짧은 시연 설정의 호출 4회가 앞선 분석·통계에서 소진되면 정책 작성이 실행되지 않을 수 있습니다. 실제 전체 흐름 배포에는 LLM_MAX_CALLS=10과 정책 출력 한도8192를 지정하고, 총액·실행별 예산은 운영 예산 안에서 유지하세요. 저장된 제안의 fallback_reason과 생성 방식이 구상안인 이유를 구분합니다.
