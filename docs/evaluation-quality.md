# 평가 품질 데이터 준비

기존 보고서의 규칙·실행 검증과 독립 기준답에 대한 실제 성능은 구분한다.
현재 이 도구는 **평가 준비 상태**만 계산한다. `/evaluation`에서 5축의 미평가 이유와 기준답 준비 현황을 확인한다. 분류·매칭·RAGAS 점수 계산은 후속 기능이다.
기준답이 없어도 실행할 수 있으며 점수는 `null`, 상태는 `not_evaluated`다.

```sh
uv run python -m eval.prepare_quality eval/fixtures/quality-synthetic.json
```

출력된 `runtime/quality/sample/<UUID>/ (실제 입력 포함 시 `local`)`에는 다섯 파일이 생긴다.

- `inputs.json`: 고정 입력과 SHA-256. 모델 실행에 기준답을 전달하지 않는다.
- `labels.json`: 데이터 해시에 묶인 검토자·평정 양식. 실제 평정은 비공개로 보관한다.
- `blind-packet.json`: 사례·개발/시험 ID를 숨긴 입력 평정 자료. 내용에서 지역이 드러날 수 있다.
- `private-key.json`: 가림 ID와 원래 ID의 매핑. 검토자에게 전달하지 않는다.
- `readiness.json`: 누락·판단불가·미해결 이견·독립 합의 건수. 모델 성능이 아니다.

다시 가져올 때 최초 고정 입력을 사용한다. 원본 입력을 수정하면 해시 검증이 실패한다.
새 데이터는 새 버전으로 만든다. 기존 보고서 schema1–5는 변경하지 않는다.
새 schema6 준비 파일은 아직 기존 `/reports` 목록에 게시하지 않는다.

```sh
uv run python -m eval.prepare_quality runtime/quality/sample/ID/inputs.json \
  --labels runtime/quality/sample/ID/labels.json
```

평정은 `judgments` JSON 배열 또는 CSV로 대체할 수 있다. `--judgments ratings.csv`를
위 명령에 추가한다. CSV 헤더는 다음과 같다.

```csv
case_id,policy_id,reviewer,value,reason,reviewed_at,provenance,policy_as_of,adjudication
```

`policy_id` 빈칸은 동네 등급 평정이며 `value`는 `1`~`5` 또는 `unknown`이다.
정책 평정은 고정 입력에 있는 정책 ID와 `suitable`, `conditional`, `unsuitable`, `unknown`을 사용한다.
`adjudication`은 `true` 또는 `false`, 날짜는 ISO 날짜다. `policy_as_of`는 입력 스냅샷과 같아야 한다.
누락과 명시적 판단불가는 서로 다른 상태다. 전체 정책 후보 범위는 입력의 `policies`로 고정한다.

검토자 양식은 기존 비교 평가와 공유한다: `id`, `expertise`, `development_participant`.
평정 출처는 `independent_review`, `rule_oracle`, `observed_outcome`, `synthetic_reference`다.
개발 참여자는 독립 평정으로 등록할 수 없다. 서로 다른 두 독립 검토자의 합의가 있어야
독립 참조로 집계하며 이견은 제3자 조정 전까지 해소하지 않는다. 원래 평정과 조정 이유를 보존한다.
독립성이 자동 인증되는 것은 아니므로 전문성과 실제 검토자 정보는 별도 확인해야 한다.
합성 입력을 사람이 평정해도 실제 지역 성능으로 사용할 수 없다.

`family_id`는 같은 원천에서 만든 월별·집단별 변형을 묶는다. 같은 계열을 개발/교정/시험에
나누면 거부한다. 계열 정보 자체가 잘못 입력되면 이 검사는 누출을 자동 발견하지 못한다.
실제 데이터·기준답·평정자는 `runtime/`에 두고 커밋하지 않는다. 공개 fixture는 명시적 합성 예제다.

가림 평정은 `blind-packet.json`의 `blind_id`를 CSV/JSON의 `case_id`에 넣는다.
가져올 때 `--key runtime/quality/sample/ID/private-key.json`으로 복원한다. 해시가 다른 키나 미등록 ID는 거부한다.
평정자는 모델 예측이나 기준답을 보지 않고 입력으로 참조를 작성한다. 원래 ID로 직접 평정한 자료도 수용하므로 가림 절차 준수 여부는 운영 기록에 남겨야 한다.

가림키로 가져온 실행은 새 가림 자료를 만들지 않고 사용한 키를 `import-key.json`으로 보존한다.
독립 평정끼리 이견이 나도 규칙으로 조정하면 최종 독립 참조로 세지 않는다. 조정자까지 독립 평정이어야 한다.

## 대시보드 조회

`/evaluation`에서 평가 자료를 선택한다. 지역·기간·방법론 필터는 기준답 분모에도 적용된다.
`GET /reports/quality`와 `/reports/quality/{UUID}`는 준비 자료를 다시 검증해 조회하며 검토자 이름·평정 이유는 반환하지 않는다. 준비 현황에는 기준답 값을 포함하지 않으며, 분류 평가 실패 사례에는 비교용 등급을 포함한다.
`source=sample`은 합성 전용 저장소, `source=current`는 현재 서버의 데이터 모드 저장소를 조회한다.
`--output-root`로 별도 위치에 저장한 파일은 자동 게시되지 않는다. 손상된 자료는 오류로 표시한다.
모델 평가가 아직 실행되지 않았으므로 모델 점수나 비교 결과를 표시하지 않는다.

서버가 sample 모드이면 `현재 서버`와 `공개 합성`은 같은 저장소를 조회한다. 새로고침은 선택한 자료가 남아 있는 한 지역·기간·방법론 조건을 유지한다.

## 추천 결정 근거

새 지역 업무의 자원 제안에서 `추천·제외 근거 확인`을 펼치면 관측 ID·값·기간,
잠정 욕구 매핑, 실제 필터 입력, 모델에 제시한 후보, 조건부 추천과 미선택, 제외 사유를 확인한다.
필터 통과는 개인 자격·접수·정원 확인이나 실제 배정을 의미하지 않는다.
기존 실행은 미기록으로 표시하며 사후에 추천 이유를 생성하지 않는다.
정책 조사 후보에는 조회 시점의 공식 상세 원문 해시가 추가된다. 지역 공통 후보는 동별 배정과 다르다.
LLM 장부의 `input`은 실제 모델에 전달한 내용이고, 전체 도구 원문과 다를 수 있다.
설명 근거 평가는 실제 `input`을 사용하며, 원문을 사후에 추가해 정당화하지 않는다.
## 분류 품질 평가

준비 명령에 `--predictions predictions.json`을 추가하면 고정 입력에 묶인 예측을 가져온다.
형식은 `dataset_hash`, `model`, `version`, `method`(rules/single/mas), `predictions` 배열이다.
배열 항목은 `case_id`, `status`(predicted/abstained/failed), `grade`(1~5 또는 null), 선택적 `run_id`다.
미등록 사례·중복·다른 입력 해시·상태와 등급 불일치는 거부한다. 가져온 모델 이름은 제출자의 메타데이터이며 실행 증명은 아니다.

대시보드는 독립 합의/조정이 끝난 참조등급만 점수에 사용한다. 없는 예측·보류·실패도 재현율 분모에 남는다.
Macro-F1은 기준이나 예측에 등장한 등급들의 F1 평균이며, MAE는 유효 예측쌍만 사용해 coverage를 병기한다.
방법론과 실제/합성 입력은 분리하며 기준답 없는 점수는 null이다. 고등급 재현율과 정밀도·검토 대상 비율을 함께 읽는다.
분류 평가를 가져온 경우 실패 사례의 기준/예측 등급을 공개하지만 검토자 이름·평정 원문은 API로 내보내지 않는다.

`부분 평가`는 전체 5축 중 분류 축을 계산했다는 의미다. 전부 미판정이어도 독립 참조가 있으면 재현율/F1은 0으로 평가하고, MAE와 정밀도의 분모가 0인 경우만 미평가로 표시한다.

## 자원 검색·매칭 품질

예측 항목의 선택적 `resources`는 `status`(completed/failed), `retrieved_ids`, `recommended_ids`(최대3),
`suitability`(정책ID→suitable/conditional/unsuitable/unknown)다. 정책은 고정 후보 범위 안에 있어야 하며 추천은 검색 결과의 부분집합이어야 한다.
자원 출력이 하나도 없는 자료는 매칭 미평가다. 자원 평가를 가져오면 다른 사례의 누락 출력도 평가 분모에 남는다.

검색 재현율과 Recall@3의 분모는 독립 평정된 적합 정책이다. 평정 coverage와 Recall@3 상한을 함께 확인한다.
미평정/판단불가는 부적합이 아니다. 미평정 추천이 있으면 정확한 적합 비율은 null과 상·하한으로 표시한다.
NDCG@3은 전체 고정 후보가 독립 평정된 경우만 계산하며 적합2/조건부1/부적합0의 선형 gain을 사용한다.
정책별 적합성 F1은 알려진 참조 3종에 대해 계산하고, 예측 unknown/누락은 별도 혼동행렬 열로 남는다.
빈 추천은 완벽한 precision이 아니며, 알려진 적합 자원이 있으면 recall0이다.

정책 입력에 선택적으로 `constraint_checks`(조건명→pass/fail/unknown)를 고정할 수 있다.
이는 결정적 도구의 기준시점 검사 기록이며 실시간 자격 판정이 아니다. 기록이 없으면 미검사로 표시한다.
정부24 공통 후보 수 확장과 별개로 이 평가는 동별 자원 추천 top3를 대상으로 한다.

적합성 분류는 전체 고정 후보에 대한 별도 과제이므로 검색되지 않은 후보의 분류도 받을 수 있다. 검색 재현율은 별도로 계산해 검색 누락을 숨기지 않는다. 적합성 Macro-F1은 기준 또는 예측에 등장한 클래스를 평균한다.

## RAGAS 설명 근거 평가

`uv sync --extra evaluation`으로 평가 전용 RAGAS 0.4.3을 설치한다. 호환성 때문에
langchain-community 0.4.1을 고정한다(0.4.2에서는 RAGAS가 가져오는 vertexai 모듈이 없어짐).
0.4.3의 지원되는 legacy metric API를 사용하며 RAGAS 1.x 전환은 별도 호환 검증이 필요하다.

```sh
uv run --extra evaluation python -m eval.run_grounding runtime/quality/local/REPORT_ID \
  --store /path/to/existing/runtime/local/events.sqlite3 --env /path/to/.env \
  --data-mode local --role workflow_analyst
```

예측의 `run_id`로 기존 성공한 live 모델 호출의 실제 `input`/`output`을 가져온다.
전체 도구 원문을 나중에 추가하지 않는다. 예측 입력과 기준답 준비 자료의 해시를 결과에 연결한다.
Faithfulness는 실제 모델 입력에 대한 충실도다. 독립 참조 문장을 `--references`의
case_id→문장 JSON으로 제공하면 Context Precision/Recall도 계산한다. 참조가 없으면 미평가다.
도구 호출·목표 달성에 대한 독립 참조 경로, 한국어 사람 평정과 judge 일치도는 아직 확보되지 않았다.
이 점수는 정책 사실성·최신성·분류 정확도나 자원 적합성 점수가 아니다.

평가 호출은 기존 `llm_calls` 장부에서 원자적으로 예약하며 SDK 자동 재시도는 끈다.
같은 runtime의 sample/local 과거 장부를 합산하고 추가 장부는 `--other-ledger`로 지정한다.
실행 중인 유료 호출은 하나의 공통 장부를 사용해야 한다. 다른 장부는 과거 기록 합산용이다.
실패/비용 미확인은 그대로 보존하며 별도 장부로 예산을 초기화하지 않는다.
`grounding-<judge UUID>.json`은 매번 새 파일로 남고 UI는 최신 파일을 보여준다.
필터를 적용해도 비용은 전체 평가 실행 비용으로 표시한다. 평가자는 같은 모델일 수 있어 편향 검증이 필요하다.

Grounding 결과와 judge 원문 장부도 비공개 평가 자료입니다. 공개 저장소에 포함하지 않습니다. 기본 누적 장부는 같은 runtime의 sample/local 중 존재하는 파일을 합산하며, 다른 위치의 과거 장부는 `--other-ledger`로 모두 지정해야 합니다. 명시한 장부가 없거나 읽을 수 없으면 실행하지 않습니다. 공급자 실패 또는 비용/호출 상한 도달 뒤에는 같은 judge 실행의 추가 유료 호출을 중단하고 나머지 지표도 실패로 보존합니다.

### 지역·시간·방법 비교

같은 폴더의 `study.json`에 `version`, `dataset_hash`, `label_hash`, `development_regions`, 공통 `conditions`, 2–3개 `arms`를 등록합니다. 각 arm은 같은 `conditions`와 기존 형식의 `predictions`, 선택적인 실행별 `telemetry`를 가집니다. 방법은 `rules`, `single`, `mas` 중 중복 없이 사용합니다. 조건은 `model`, `tools_version`, `catalog_hash`, `max_calls`, `max_usd`입니다. 카탈로그 해시는 `digest({case.id: case.policies for case in dataset.cases})`로 계산합니다. 비규칙 arm 모델과 모든 조건이 같아야 하며 서로 다른 방법에 같은 run ID를 재사용할 수 없습니다.

`uv run python -m eval.quality_study runtime/quality/local/<자료 UUID>`로 검증·계산하거나 대시보드에서 조회합니다. 기준답이 없으면 품질 차이는 미평가입니다. 예측 누락·실패는 분류 비교에서 성공으로 처리하지 않습니다. 각 지역·기간·방법론·실제/합성·split별로 계산하고, 같은 원천 계열 안의 사례 차이를 평균한 뒤 계열에 동일 가중치를 줍니다. 추천 NDCG는 두 방법 모두 계산 가능한 사례만 짝지으며 그 계열 수를 표시합니다. 새 오류와 수정된 오류는 사례 수로 별도 표시합니다.

강남·춘천 및 등록된 개발 지역은 외부 일반화로 표시하지 않습니다. 다른 실제 test 지역도 **등록된 미사용 지역 시험**일 뿐 개발 이력의 완전성이 자동 검증되는 것은 아닙니다. `timing`은 case ID별 `input_available_at <= predicted_at < outcome_available_at`의 시간대 포함 시각을 받습니다. 예측은 목표 월 시작 전, 결과 확보는 그 월 끝 이후여야 합니다(월 경계 UTC). 실제 test 사례 전체에 시점 기록이 있어야 사전 예측 시험으로 표시하며 합성 월은 실제 미래로 승격하지 않습니다.

선택적인 telemetry는 `run_id`, `cost_usd` 또는 null, `latency_seconds` 또는 null을 가집니다. 공유 실행을 여러 사례로 복제해도 비용을 다시 더하지 않습니다. 비용·p50/p95는 필터 전 전체 실행 범위이며 가져온 기록임을 표시합니다. 신뢰구간이나 통계적 유의성은 계산하지 않으며 단순한 양의 차이를 입증된 MAS 효과로 부르지 않습니다.

개발 지역 목록이 비어 있으면 새로운 실제 test 지역도 개발 이력 미확인으로 남깁니다. 강남·춘천 보호 규칙은 이미 개발에 사용한 이 프로젝트의 이력을 반영하며, 그 외 지역은 등록된 개발 이력과 대조합니다. 시점 기록 수를 전체 사례 수와 함께 표시합니다.


### 대시보드에서 실행·저장

`/evaluation`에서 자료를 선택하고 **평가 실행·저장**을 누릅니다. 기본은 모델 비용 $0인 결정적 평가입니다. 입력과 라벨·예측·비교 프로토콜을 비공개 스냅샷으로 고정한 뒤 계산합니다. 기준답 없는 지표는 계산 완료 후에도 미평가입니다. 원본 파일 변경은 저장 결과를 바꾸지 않습니다.

현재 서버가 live이고 선택 의존성·모델·가격·누적 예산이 설정된 경우 RAGAS를 포함할 수 있습니다. 실행 전 최대 예약 견적을 표시하고, 실제 모든 호출은 기존 서버 장부와 같은 runtime의 다른 모드 장부를 합산합니다. 별도 위치의 과거 비용 장부가 있다면 대시보드 대신 `eval.run_grounding --other-ledger`를 사용하십시오. 격리 evaluation_id 장부에서 유료 대시보드 실행은 금지합니다. 참조 텍스트 기반 지표는 CLI로 제공한 별도 기준답이 있어야 계산됩니다.

작업은 기존 SQLite에 저장합니다. 동일 자료·평가 설정·평가기 버전 요청은 같은 작업을 반환하며 중복 클릭과 새로고침으로 재과금하지 않습니다. 로컬 단일 앱 프로세스용입니다. 서버 재시작 시 진행 중이던 작업은 실패로 보존하고 자동 유료 재시도하지 않습니다. 실패 뒤 다시 누르는 것도 같은 실패 기록을 반환합니다. 재평가가 필요하면 예측/데이터 버전을 새로 등록해 의도를 남깁니다. 다중 worker 배포 전에는 소유권 lease가 필요합니다.

이력에서 두 저장 결과를 선택하면 입력·기준답·평가 방식·평가기 버전이 맞는 경우에만 나란히 확인합니다. 서로 다른 실행 조건의 단순 비교는 MAS 효과의 증명이 아닙니다. 사례 상세의 **추천 근거 조회**는 기록된 run ID와 정확한 evidence ID를 대조하여 원래 제안의 근거 카드를 보여줍니다. 기록이 없거나 다른 모드이면 설명을 만들어내지 않습니다.

API: `GET /reports/quality/{id}/preflight`, `POST /reports/quality/{id}/jobs` (`suite: deterministic|grounding`), `GET /reports/quality/{id}/jobs`, `GET /quality-jobs/{id}`. 파일과 원문·개인 평정은 비공개 runtime에 남고 응답에는 공개용 결과만 포함합니다.

## 정부24 후보 5건과 정책 설계 평가

기존 `predictions.json`의 카탈로그 추천은 최대3건 계약을 유지합니다. 별도 `policy-candidates.json`은 같은 예측 형식과 고정 후보 집합을 사용하되 최대5개 고유 ID를 허용합니다. 준비 명령에 `--policy-candidates FILE`을 주면 검증 후 저장합니다. 평가 화면과 저장 작업에서 정부24 정책 후보의 Recall@5·NDCG@5·적합성 분류·미평정 후보·검색 누락을 별도로 보여줍니다. 모집단은 고정 후보 중 독립 평정된 적합 정책입니다. 등록 전체 정책의 재현율로 해석하지 않습니다.

정책안은 `--policy-drafts FILE`로 별도 등록합니다. 형식은 `{dataset_hash, cases:[{case_id,run_id,document}]}`이며 document는 저장된 정책 설계 결과 또는 담당자 수정 버전입니다. 입력·원문·정책안 버전을 대조합니다. 첨부 근거 대조 성공은 실제 정책 효과가 아닙니다.

선택적인 `--policy-draft-ratings FILE`은 `{input_hash,reviewers,ratings}` 형식입니다. `input_hash`는 `eval.policy_design_quality.quality(frozen,inputs)['input_hash']`로 확인합니다. reviewers는 기존 `id/expertise/development_participant` 계약입니다. ratings의 각 행은 `case_id/version/reviewer/reviewed_at(YYYY-MM-DD)/scores/reason`을 담습니다. scores는 `grounding`, `feasibility`, `clarity`, `equity`, `evaluation_plan` 다섯 축 모두에 1–5 정수 또는 null입니다. 1은 중대한 보완, 3은 조건부 수용, 5는 충분한 근거·구체성을 뜻하는 잠정 기준입니다. 평가자는 결과 출처와 개발 방법을 가린 사본으로 독립 평정하고, 문장 유창함만으로 높은 점수를 주지 않습니다.

개발 참여자의 점수는 독립 평정으로 세지 않습니다. 축별 독립 평정이 2명 미만이면 미평가, 2점 이상 차이가 있으면 불일치와 범위를 표시하고 평균을 숨깁니다. 실제 시행 효과는 계속 미평가입니다. 같은 실행의 `policy_design` 최종 모델 응답도 RAGAS의 저장 입력 기준 충실도 평가에 포함되며, 공식 사실성·정책 적합성·사람 평정을 대신하지 않습니다. 평가 작업은 정책 후보·초안·평정을 함께 고정해 재실행 중 변경을 차단합니다.

### 실제 연동 검증의 해석
정책 API 응답, 정확 인용, 모델 호출 성공과 대상 집단 적합성을 따로 평가합니다. 2026-10-22 로컬 검증에서 정부24 22페이지(10,958건) 갱신, 실제 상세 5건 묶음, 유사사례 4건 조회를 확인했습니다. 실제 지역 업무의 정책 후보에는 청년 업무에 맞지 않는 노인 정책도 포함됐습니다. 따라서 독립 후보 적합성 라벨 없는 Recall/Precision을 성공률로 제시하지 않습니다. 좁은 복합어 검색이 0건인 정책 설계 시험은 참고 근거 부족으로 초안을 보류했으며, 이를 현실의 정책 부재나 보고서 생성 성공으로 세지 않습니다.
