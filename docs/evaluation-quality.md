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
`GET /reports/quality`와 `/reports/quality/{UUID}`는 준비 자료를 다시 검증해 조회하며 검토자 이름·평정 이유·원본 기준답 값은 반환하지 않는다.
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
