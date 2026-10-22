# 개발·실행 안내

프로젝트 목적과 화면 흐름은 [README](../README.md), 역할과 저장소 구조는 [아키텍처](architecture.md)에 있습니다.

## 키 없는 합성 시연

Python 3.12 이상, uv 0.8.8 이상, Node.js 22 이상을 준비합니다. 새 체크아웃에서 실행하며, 기존 `.env`가 있다면 복사 명령으로 덮어쓰지 않습니다.

```sh
make install
test -e .env || cp .env.example .env
make sample
make dev
```

대시보드는 `http://127.0.0.1:5173`, API는 `http://127.0.0.1:8000`, API 명세는 `/docs`입니다. `Ctrl-C`로 두 서버를 종료합니다. 기본 예제는 `sample/fake/fixture`이며 외부 키 없이 통신 흐름을 확인합니다. 정부24 미연결 상태를 실제 정책 결과로 대체하지 않습니다.

`.env.example`의 호출 한도는 4회입니다. 역할이 많은 지역·정책 흐름에서는 예산 부족으로 보류될 수 있습니다. 전체 역할 흐름 시험에는 설정이 허용하는 최대 10회를 사용하고, live에서는 출력 토큰·실행별/누적 예산·현재 모델 가격 기준도 함께 확인합니다. 예산을 자동 증액하지 않습니다.

## 실제 입력과 API

[자료 반입](data-policy.md)으로 실제 입력과 v3 카탈로그를 준비하고 [LLM 설정](llm-usage.md), [정부24 설정](policy-tools.md)에 따라 `.env`를 구성합니다. 키가 있다는 사실만으로 실제 지역 자료가 준비되는 것은 아닙니다.

```sh
make dev-live
# 기본 포트가 사용 중이면:
uv run python -m scripts.dev --live --api-port 8050 --ui-port 5230
```

`--live`는 실제 자료·모델·가격·예산·정부24 키를 확인하고 `local/live/v3`로 실행합니다. 실패하면 합성 자료로 대체하지 않습니다. LLM fake/live 설정과 정부24 API 연결은 별개입니다.

| 데이터 | 위치 |
|---|---|
| 공개 합성 입력 | `data/sample/` |
| 비공개 실제 입력 | `data/local/` |
| 실행·트레이스·체크포인트 | `runtime/{sample,local}/` |
| 품질 평가 입력·참조·예측 | `runtime/quality/{sample,local}/` |
| 평가 작업별 동결 산출물 | `runtime/quality-jobs/{sample,local}/` |

기존 비용 장부를 삭제하거나 새 DB로 바꿔 누적 비용을 초기화하지 않습니다. 실제 입력을 포함한 프롬프트·트레이스·화면 캡처 역시 비공개 자료입니다.

## 테스트와 평가

```sh
make test                         # Python 테스트 + TypeScript 검사/빌드
cd frontend && npx playwright install chromium && cd ..
make e2e                          # 별도 sample/fake 서버와 브라우저
make check                        # 위 검증 + 커밋된 공개 파일 검사
```

E2E 기본 포트는 8000/5173이며 다른 서버가 쓰고 있으면 분리합니다.

```sh
E2E_API_PORT=8040 E2E_UI_PORT=5220 make e2e
```

기능 테스트와 성능 평가는 별개입니다. 평가별 입력·기준답과 해석 범위는 [평가 체계](evaluation-quality.md), [고정 평가 기록](evaluation.md), [협업 비교](agent-comparison.md)를 확인합니다.

| 명령 | 목적 |
|---|---|
| `make classify` | 생성한 합성 집단의 결정적 단계 계산 |
| `make eval-v2` | v2 합성 계약 60건 × 2회 |
| `make eval-temporal` | 시간순 합성 신호와 기준선 비교 |
| `make eval-workflow` | 지역 업무 평가 |
| `make eval-collaboration` | 기존 단일 제안·협업 계약 비교 |
| `make eval` | 기존 v1 HTTP·브라우저 시나리오 40건 |

기존 v1의 명시적 척도 응답은 별도 MCP가 필요합니다. 설정이 없으면 실패를 포함한 보고서와 종료 코드 2가 나올 수 있으며 실제 개인 판정 성능으로 해석하지 않습니다. 새 품질 평가의 준비·실행 명령은 [평가 체계](evaluation-quality.md)를 따릅니다.

## API와 스키마

API 입력은 `/docs`에서 확인합니다. 일반 제안은 `/runs/{id}/approval`의 `snapshot_version`을 기준으로 검토하며 오래된 버전의 결정은 거절합니다. 정책안 검토는 별도 `/runs/{id}/policy-design/review` 계약을 사용합니다. 승인 후 연계도 로컬 기록이며 실제 기관 전달을 뜻하지 않습니다.

Pydantic 계약 변경 후 `make contracts`로 프런트엔드용 JSON Schema를 갱신합니다. 평가 기준답은 실행 입력에 넣지 않습니다. [데이터·API 계약](contracts.md)

## 공개 파일과 제출

```sh
uv run python scripts/install_hook.py
uv run python scripts/check_public.py --tracked
```

hook 설치는 기존 hook을 덮어쓰지 않습니다. 기본 검사는 staged Git blob, `--tracked`는 커밋된 HEAD를 검사합니다. 지정된 비공개 경로와 흔한 비밀값 패턴을 검사하지만, 모든 개인정보나 임의 경로에 복사된 민감 자료를 탐지하는 것은 아닙니다.

검사한 커밋에서 공개 archive를 만듭니다. 작업 폴더 전체를 압축하지 않습니다.

```sh
git archive --format=zip --output=../beyond-hello-mas.zip HEAD
```

개인 로컬 계획·실제 자료·환경파일·SQLite·실행 산출물은 제출물에 포함하지 않습니다. Vercel 등 원격 배포는 [배포 관문](deployment.md)의 별도 검증이 필요합니다.
