# LLM과 MCP 연동

## 지금 실행 가능한 범위

기본 sample/fake 경로는 키 없이 실행됩니다. fake 설명·질문 라우팅은 결정적 테스트 대역이며 OpenAI 성능 근거가 아닙니다. 2026-10-18에 `gpt-6-luna`로 정책 worker의 실제 OpenAI→MCP 관측→종료 smoke를 확인했습니다. 이는 전체 모델 성능 평가가 아닙니다. 실행 환경별 키·모델·가격·예산은 비공개 `.env`에서 설정하며 저장소에는 기본 모델을 강제하지 않습니다.

## OpenAI 설정과 한도

- `LLM_MODE=live`, `OPENAI_API_KEY`, `OPENAI_MODEL`: 사용 가능한 모델 ID를 직접 선택합니다. 날짜 스냅샷을 제공하면 고정하고, 별도 스냅샷이 없으면 반환 모델 ID를 trace에 기록합니다. 임의 기본 모델이나 자동 대체 모델은 없습니다.
- `LLM_BUDGET_USD`: 저장소의 모드별 실행 DB에 누적된 예약액 기준 상한. 기본값 0으로 실제 호출을 막습니다.
- `INPUT_USD_PER_MILLION`, `OUTPUT_USD_PER_MILLION`, `PRICE_VERSION`: 선택 모델의 확인된 표준 가격과 확인일/출처 버전을 지정합니다. 현재 숫자를 추측해 고정하지 않았습니다.
- 실행당 최대 4회, 출력 최대 1,024토큰, 입력(프롬프트·payload·schema) 최대 24,000바이트, 요청 timeout 30초가 기본입니다. SDK 자동 재시도는 0회입니다.
- 호출 전 입력 바이트 수+8,192 여유분 및 최대 출력 토큰으로 보수적인 금액을 예약합니다. 실패/중단된 호출의 예약도 유지하고 같은 요청을 재시도하지 않습니다. 예약액은 실제 청구액이 아니며 공급자 비용 제어를 대체하지 않습니다. 실제 usage가 더 크면 장부에 상향 반영합니다.
- 성공 시 모델 응답의 raw usage와 표준 입력 가격 기준 보수적 비용 추정치를 기록합니다. 캐시 할인 등은 raw usage로 후속 평가에서 구분해야 하며 추정치를 정확한 청구액으로 쓰지 않습니다.

Responses API의 `responses.parse`와 Pydantic schema를 사용하고 서버 저장은 `store=False`로 요청합니다. 모델별 지원 파라미터를 확인하기 전 temperature/seed를 임의 전송하지 않습니다. 설정할 모델의 구조화 출력/토큰 한도와 계정 접근 가능성은 실제 smoke 때 확인해야 합니다. [공식 구조화 출력 문서](https://developers.openai.com/api/docs/guides/structured-outputs), [Responses API](https://developers.openai.com/api/reference/python/resources/responses).

## 역할과 검증

분류 설명 schema에는 summary/causes/needs/review_required만 있고 숫자 단계 필드가 없습니다. 추천 설명은 결정적 후보 ID 전체와 실제 field/value 근거를 그대로 참조해야 하며 추가 ID/다른 필드는 거부합니다. 자유 서술의 모든 주장까지 자동으로 검증했다는 뜻은 아니므로 담당자 검토가 필요합니다.

안내 초안은 승인 전에 만들어 snapshot에 포함합니다. 승인 후 문구나 후보를 새로 생성하지 않습니다. 질문 라우팅은 classify/match/link/history/human 중 하나만 허용합니다. history는 현재 모드 DB만 조회하고 match는 명시적 match_request를 요구합니다. link 요청은 일반 승인 경로로 들어가며 라우팅 문구로 승인을 우회할 수 없습니다. 이 기존 경로에는 반복 계획 루프가 없습니다. 별도 `policy` 시나리오는 Supervisor 위임 아래 `policy_decision` 구조화 출력을 반복하며 실제 정책 MCP 관측으로 다음 행동을 선택합니다([정책 ReAct](policy-tools.md)).

프롬프트 파일, hash, 모델, 입력/출력, 토큰/지연, 재시도 여부와 오류 유형을 해당 모드 DB trace에 보존합니다. API 키/SDK 예외 원문은 기록하지 않습니다. 같은 run의 성공한 동일 호출은 재개 시 재사용하며, 실패 또는 미확정 호출은 새 run에서 명시적으로 다시 실행해야 합니다. LangSmith tracing은 비활성화합니다.

## 기존 LSIS-6 MCP

MCP 프로젝트는 별도로 설치합니다. 비공개 소스나 패키지를 이 공개 저장소에 복사하지 않습니다. 설치한 MCP의 Python 경로와 프로젝트 경로를 `.env`의 `MCP_PYTHON`, `MCP_CWD`에 지정합니다. 기본 전송은 해당 Python의 `-m beyond_hello_mcp.server` stdio입니다.

`score(scale_id="lsis-6", responses=...)`에 실제로 입력된 q1~q6 정수 선택값만 전달합니다. 채점이나 역채점을 재구현하지 않습니다. 응답 누락은 pending이고 부분 응답/잘못된 값은 입력 오류입니다. 결과의 loneliness/support/network, 두 위험 결과, 척도 버전/출처/주의문을 보존합니다. 개인 척도를 집단 5단계로 환산하지 않습니다.

`MCP_ALLOW_FALLBACK=true`일 때 전송/timeout 오류만 동일 Python·cwd의 `beyond_hello_mcp.scoring.score`로 폴백합니다. 전후 scoring.py와 척도 파일 hash가 같은지 확인합니다. MCP 입력/프로토콜 오류에는 폴백하지 않습니다. 반환 버전은 LSIS-6 1.0.0 계약을 검사합니다.

개인 추천 강도는 임시 운영 매핑입니다. 명시적 척도 결과의 위험 라벨이 있으면 high, 없으면 low를 사용하고, 확인된 욕구·나이·관할이 있는 경우에만 매칭합니다. 외로움 라벨은 emotional, 사회적 고립 라벨은 relationship 욕구에 연결합니다. 이는 임상 진단/개입 타당성 검증이 아니며 최종 정책 확인이 필요합니다.

## 검증

`make test`는 키 없는 fake/오류 fixture를 검사합니다. 로컬 MCP 설정 후 아래 명령은 실제 stdio 호출, 동일 패키지 폴백 동등성 및 사례 그래프 연결을 검사합니다. CI에 비공개 MCP가 없으면 해당 두 테스트만 명시적으로 skip합니다.

```sh
uv run pytest tests/test_agents.py::test_actual_mcp_and_same_package_fallback tests/test_graph.py::test_case_with_actual_scale_keeps_two_results_and_candidates
```

현재 로컬에서 두 실제 MCP 테스트를 통과했습니다. 정책 worker의 실제 OpenAI 소규모 호출은 아래와 같이 검증했지만 전체 평가와 청구서 대조는 미실행입니다. fake 성공이나 MCP 성공을 live 모델 검증으로 합산하지 않습니다.

## 동결한 실행 근거

공개 반복 평가는 fake-v1이며 OpenAI 요청/토큰/청구 비용은 없습니다. 모델 스냅샷과 실제 단가는 미확정이므로 임의 값을 채우지 않았습니다. 네 역할 프롬프트의 hash와 규칙·카탈로그·입력 hash는 [고정 보고서](evaluation.md#고정-결과-2026-10-18)에 있습니다. 실제 MCP package 0.1.0 / LSIS-6 1.0.0 연동은 수행했으며, 비공개 MCP 소스는 제출물에 포함하지 않습니다. 공개 자료만으로는 명시적 척도 16건을 완료할 수 없고 해당 실패를 표시한 partial 평가를 재현할 수 있습니다.

## 정책 worker live smoke (2026-10-18)

[공식 GPT-6 Luna 모델 안내](https://developers.openai.com/api/docs/models/gpt-6-luna)의 모델 ID, Responses/구조화 출력 지원과 가격을 확인한 뒤, 격리된 sample 실행에서 합성 요청으로 검사했습니다. `policy_coverage` 관측 후 정부24 인증키 미설정을 확인하고 후보 없이 정상 종료했습니다. 실제 모델 호출 2회, 오류 0건, 반환 모델 `gpt-6-luna`, 결과 `no_verified_candidates`입니다. 정책을 지어내지 않는 동작을 검증했으며 실제 정책 적합성이나 전체 시나리오 정확도 검증은 아닙니다.

이 검증의 로컬 초기 누적 예산은 $0.10, 출력 한도 4,096토큰, 호출 timeout 60초입니다. 공식 표준 입력 $0.10/출력 $0.50(백만 토큰당), 캐시 쓰기 $0.125를 고려해 입력 장부 단가를 보수적으로 $0.125로 설정했습니다. 두 호출의 usage 기반 보수적 추정은 $0.000267375, 호출 전 예약 합계는 $0.007040875입니다. 실제 청구액과는 구분합니다. 지역/처리 등급별 할증이나 가격 변경 시 단가를 다시 확인해야 합니다. raw usage와 실행 근거는 비공개 runtime에 보존합니다.
