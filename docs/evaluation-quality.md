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
