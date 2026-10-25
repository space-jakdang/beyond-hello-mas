# 비공개 운영 입력 패키지

현재 지역 분석은 MDIS·복지패널 개인 원자료를 서버에서 직접 읽지 않습니다. 해당 조사 자료가 지표 설계·오프라인 검증의 근거라는 사실과 런타임 파일 의존성은 구별합니다. 이 도구는 라이선스를 판정하거나 원천 지수를 재산정하지 않습니다.

| 기능 | 런타임 입력 | 포함 방식 |
|---|---|---|
| 실제 동네·집단 분석, 통계, 근거 조회 | `local/segments-v3.parquet` | 최소 패키지 |
| 주간 카드 신호 | `local/seohee/card_weekly_signals.csv`, `import.json` | 기존 해시 검증 후 필요한 파일만 표준 경로로 복사 |
| 2026-10-25 지역 판정 v4 | `local/segments-v4.parquet`, `local/seohee/card_alarm_weekly.csv`, `local/import.json` | 명시적으로 선택한 v4 reader가 각 artifact 해시와 데이터 버전을 확인 |
| 지역 자원 후보 | `local/resources-v3.csv` | 최소 패키지 |
| 실제 지도 | `data/geography/` 경계·manifest·라이선스 | 기존 코드 배포, 패키지 검증 시 동일 경계 확인 |
| 단계·연령 규칙, 프롬프트 | `rules/`, `backend/prompts/` | 코드 버전과 함께 배포 |
| 정부24·LLM·정책 보고서 | 위 분석 입력 + 서버 비밀 설정 + 새 실행 저장소 | 키·DB·기존 보고서는 패키지에 포함하지 않음 |
| 개인 사례·legacy-v1 분석 | 별도 MCP/`segments.parquet` | 이번 지역 서비스 패키지 범위 밖 |
| 미래/평가 | 관측 입력을 참조하는 별도 실행 결과·평정 | 입력 패키지에 기존 실행 결과를 복사하지 않음 |

통계 근거는 현재 분석 결과를 재사용합니다. 새 외부 통계가 자동 수집되거나 모든 개인 사례 기능이 준비된다는 뜻은 아닙니다. 실제 지원 자격·방법론 타당성은 파일 무결성 검사와 별도입니다.

## 생성과 확인

로컬의 비공개 JSON에 아래 네 문자열을 기록합니다. `sources`에는 원천/변환 버전·확인 기록 위치, `disposal`에는 대회 종료 후 별도 안내와 백업 폐기 조건을 적습니다. 확인 중이면 `pending`, 실제 확인했다면 `private_contest_use_confirmed`를 사용합니다. 파일을 생성할 수 있다는 사실은 서버 반입 승인이 아닙니다.

```json
{"purpose":"공모전 비공개 서비스", "sources":"원천과 변환 버전 및 확인 기록", "permission_status":"pending", "disposal":"대회 종료 후 별도 안내에 따라 사본과 백업 폐기"}
```

```sh
uv run python -m scripts.runtime_package build --source /private/input --destination /private/releases/input-v1 --provenance /private/provenance.json
uv run python -m scripts.runtime_package verify /private/releases/input-v1
```

`source`는 `local/`의 부모입니다. 출력은 새 버전 디렉터리만 허용하며 기존 입력을 덮어쓰지 않습니다. 입력 원천의 주간 해시, 출력 파일 목록·해시, 실제 경계 결합과 카탈로그를 검사합니다. 목적지 생성 중인 디렉터리를 서비스에 연결하지 마세요. 성공한 버전만 `INPUT_ROOT`로 지정하고, 실행 중 파일을 수정하지 않습니다. 원자적 활성화는 서버를 중지하고 검증된 버전 경로를 바꾼 뒤 재기동하는 절차입니다. 실패한 기존 운영 버전은 그대로 남습니다.

패키지와 provenance는 비공개 저장소에서만 다룹니다. 공개 Git·CI artifact·브라우저 정적 폴더·컨테이너 이미지에 넣지 않습니다. 기존 원본·MDIS 원자료·로컬 SQLite·전체 서희 전달 묶음은 복사하지 않습니다. 파일 해시는 변조 탐지용이며 발급자의 전자 서명이나 이용 권한 증명이 아닙니다.

실제 데이터 누락 시 검증을 실패시키며 sample로 자동 대체하지 않습니다. 지수 산식·단계·집단 의미는 기존 방법론을 유지합니다. 현재 자료의 47개 읍면동/8집단 수는 운영 기준선이며 미래 패키지에 고정된 숫자 검증으로 강제하지 않습니다. 월이 없는 집계를 월별 관측으로 바꾸지 않습니다.


## 지역 실자료 패키지 v2

새 지역 자료는 기존 v3 입력과 섞지 않고, 강남 22개 동과 춘천 25개 읍면동의 검증 대상만 포함하는 버전별 패키지 2로 만든다. 허용 파일은 local/segments-v4.parquet, local/resources-v3.csv, local/seohee/card_alarm_weekly.csv, 그리고 버전·원천 기간·생성 코드·입력/출력 해시를 담은 import.json이다. 기존 자원 카탈로그는 전달본과 해시가 같을 때만 재사용한다. 원천 파일 전체나 개인 단위 결과를 런타임 패키지에 추가하지 않는다.

새 서버 실행은 패키지 버전, 데이터 모드, 판정 버전과 기대 입력 해시를 함께 고정한다. 실제 자료가 없는 배포는 시작을 실패시키며 sample로 대체하지 않는다. 과거 v3 실행 조회는 유지하되 v4 업무의 입력으로 v3를 자동 선택하지 않는다. 패키지·provenance·실제 데이터는 비공개 서버 경계에만 둔다. 공개 Git, CI artifact, 정적 frontend, 컨테이너 이미지 또는 로그에 실자료와 payload를 포함하지 않는다.

현재 런타임 패키지 전달 제한(인코딩 48 KiB, 해제 8 MiB)을 최종 v2 결과에 적용한다. 인코딩 제한을 넘을 때만 Render Secret File 등 서버 전용 전달 경로를 사용한다. 제한을 높이거나 입력 일부를 빼서 검사를 통과시키지 않는다. 호스트를 고른 뒤에는 그 플랫폼의 용량·마운트 경로·재시작 동작을 다시 확인한다.

공개 CI는 새 스키마를 검증하는 고정 seed 합성 입력만 사용한다. 실제 자료 검증은 접근 통제된 로컬/비공개 환경에서 실행하고 레코드 대신 패키지 해시, 집계 건수, 통과 여부만 공개 증거로 남긴다. 입력 해시는 파일 동일성 확인값이며 이용 권한이나 출처의 전자서명은 아니다.

### v4 집계 입력 만들기

변환기는 지정 전달본의 동 단계, 서울 구조 위험 집계, 주간 카드 집계 CSV를 검증한다. 단계 artifact와 V/N 비율·단계·경보·기준선을 보존한 카드 CSV만 새 목적지에 쓰고, 선택한 원천 해시를 전후 대조한 뒤 import.json과 함께 새 패키지를 원자적으로 완성한다. v4 reader는 schema/dataset version과 각 파일 해시를 확인한다. 목적지는 이미 존재하면 거부한다. 개인 단위 파일과 나머지 전달 폴더는 복사하지 않는다.

```sh
uv run python -m scripts.export_seohee_v4 --source /private/input/agent-bundle --destination /private/releases/seohee-20261025
```

검증된 버전은 Settings.input_root를 목적지로 지정해 읽는다. 원천 자료는 읽기 전용으로 두고 출력 디렉터리를 원천 폴더 안에 만들지 않는다.
