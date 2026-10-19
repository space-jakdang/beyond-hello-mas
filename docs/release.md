# 제출 재현 기록

최신 결과는 아래 **v2 제출 후보**에 정리했다. 앞부분은 v1 당시의 검증 기록이며 현재 상태와 구분한다.

공개 sample/fake 시연용 제출입니다. 배포나 실제 기관 전달을 포함하지 않습니다. PR-01~10의 구현을 develop에 통합했고 이 문서 변경은 평가 코드에 영향을 주지 않습니다. 고정 평가는 PR-10 구현 커밋 `fca9bfc`에서 실행했습니다. squash 통합 커밋은 `d2b6200`입니다.

공개 보고서 두 개는 [평가 문서](evaluation.md)에 연결되어 있습니다. 캡처는 sample/fake만 사용합니다. 관찰·콘솔은 E2E 시나리오, 평가 캡처는 두 번째 고정 보고서 `4795088f-3bcb-460d-a424-816b0db3b7fe`입니다. 모델 키, 실제 집계, private MCP, 개인 데이터, runtime/DB, 로컬 계획은 제출 대상이 아닙니다.

## 재현 방법

새 clone에서 README의 `make install`, `make sample`, Chromium 설치, `make check`를 실행합니다. `make check`의 E2E가 health와 실제 화면을 검증합니다. 공개 자료만 있는 `make eval`은 MCP 응답 16건을 실패로 표시한 partial 보고서(40건 분모, 종료 2)를 생성합니다. 별도 설치한 MCP가 있으면 전체 실행을 재현할 수 있습니다. OpenAI live는 키·모델·가격·예산을 정한 뒤 별도로 실행합니다.

## 제출 파일 확인

```sh
uv run python scripts/check_public.py --tracked
git ls-tree -r --name-only HEAD > ../beyond-hello-mas-files.txt
git archive --format=zip --output=../beyond-hello-mas.zip HEAD
```

manifest와 zip은 같은 커밋에서 생성해야 합니다. 로컬 작업 폴더 전체를 압축하지 않습니다. 파일명 검사와 비밀 패턴 검사는 모든 개인정보를 탐지하지 못하므로 공개 캡처와 보고서는 별도 검토합니다.

## v1 제출 당시 미완료 검증

실제 OpenAI 평가/모델 스냅샷/가격 검증, 독립 사람 정답과 적합성 평가, 간접 위기 표현 검출 목표는 미완료입니다. Claude 교차 리뷰는 OAuth 인증 만료로 실행하지 못했습니다. 이후 PR은 사용자 진행 지시에 따라 자체 Ponytail 검토와 테스트 결과로 통합했으며 교차 리뷰 통과로 기록하지 않습니다. develop → main 제출 PR은 이 한계를 명시하고 별도로 준비합니다.

## 깨끗한 clone 검증 결과

2026-10-18 문서·보고서 커밋 `e08ee64`를 `git clone --no-local`로 새 임시 디렉터리에 복제했습니다. 기존 venv/node_modules/.env/runtime/로컬 계획을 가져오지 않고 잠금 파일로 설치했습니다. 패키지 다운로드 캐시와 OS의 Chromium 설치 캐시는 재사용했으므로 완전히 별도 컴퓨터를 시험한 것은 아닙니다.

- `make install`, `make sample`, Chromium 설치 성공.
- `make check`: Python 64 passed / private MCP 2 skipped, TypeScript/Vite build 성공, 브라우저 E2E 5 passed, HEAD 공개 검사 통과.
- `make eval`: 공개 입력 40건을 유지한 partial 보고서, 완료24/실패16, 예상 종료 코드 2. 명시적 척도의 private MCP 미설정 때문에 실패하며 누락을 성공으로 처리하지 않음.
- 공개 Markdown 로컬 링크 누락 0건. 최종 보고서에 개인 로컬 경로/키 없음. 고정 평가 코드와 제출 코드의 기능 diff 없음.

이 기록 추가는 문서만 변경합니다. 최종 PR CI로 공개 파일 검사와 전체 테스트를 다시 확인합니다.

## 동네별 대시보드 후속 확장

후속 PR에서 읽기 전용 분석 API와 출처가 고정된 공개 경계, 반응형 SVG 지도, 연령별 상세·월별 추이·URL 복원·분석 재조회를 추가했습니다. 기존 고정 평가의 분류/매칭/에이전트 코드는 변경하지 않았습니다. 실제 local 지도의 검증 캡처는 runtime/local에만 보관하며 공개 제출에 포함하지 않습니다. 기존 `457b1e4` ZIP과 캡처는 이전 제출 스냅샷이므로 최신 기능 제출 시 현재 develop의 tracked 파일로 다시 archive해야 합니다.

## v2 제출 후보

기존 v1 고정 결과는 유지한다. v2는 자료 반입, 원천별 지역 단계, 주간 카드 신호, 개인 MCP 계약, 행정 접수·인계, 단계·체납 자원 매칭, 8집단 대시보드, 60건 계약 평가를 추가했다. 공개 자료는 합성 입력·계약·코드·검증 보고서·sample 캡처이며 실제 입력과 로컬 결과는 포함하지 않는다.

`make eval-v2` 결과는 [v2 평가 기록](evaluation.md)에 연결되어 있다. 실제 개인 MCP v0.2·새 문항 응답 추출·전문가 적합성은 미검증이다. 청년 점수표 AUC 0.825는 전달 자료의 외부 모델 수치이며 MAS 평가 결과가 아니다. 제공 데이터는 어디·언제의 탐지, 외부 자료와 개인 판정은 누구·얼마나의 판단을 담당한다.

`develop → main` 릴리스 PR은 draft로 유지한다. 제출 압축파일은 검사한 Git 커밋의 tracked 파일만 `git archive`로 만들며 `.local-plans`, `.env`, `data/local`, `runtime`, `eval/local`을 포함하지 않는다.

### v2 최종 확인 (2026-10-19 KST)

- Python 125 passed(설치된 기존 LSIS-6 MCP 연동 2건 포함), TypeScript/Vite build, 브라우저 E2E 13 passed. 공개 clone에서는 private MCP 2건이 skip된다.
- 깨끗한 평가 코드 `4402b29`에서 60개 합성 시나리오를 두 번 실행해 코드·입력·라벨·결과 hash가 일치했다. 실제 개인 판정·LLM 문항 추출·사람 적합성은 N/A다.
- 실제 정부24 MCP로 22페이지 10,969건을 수집했다. 선택한 5개 관할은 중앙 1,049 / 서울 72 / 강남 18 / 강원 62 / 춘천 23건이다. 각 관할 한 건씩 상세·지원 조건 조회가 live로 성공했다. 이는 등록 API 범위의 수집이며 모든 현실 정책이나 남은 정원을 보증하지 않는다.
- 실제 OpenAI 정책 worker는 검색 → 상세 확인 → 종료를 수행해 근거가 있는 정책 1건을 반환했다. 실행 `fe6ce98e-c7f8-4caa-8f2d-9ba6be508f57`, completed, live 상세, 오류 0건. 기존 누적 예산을 유지했으며 전체 live 평가는 수행하지 않았다.
- 외부 MCP의 실제 도구 목록은 `list_scales`, `get_scale`, `score`다. 새 `assess_stage`·`priority_score`는 아직 없으므로 실제 개인 판정 완료로 표시하지 않는다.
- [8집단 화면](screenshots/groups-v2.png)과 [v2 평가 화면](screenshots/evaluation-v2.png)은 sample/fake로 캡처했다. 실제 집계·개인 정보·키를 포함하지 않는다.

v2 구현 PR(01–08)은 Claude Code Opus 교차 리뷰와 Ponytail 검토를 거쳤다. 마지막 제출 문서 PR(09)도 사용 한도 해제 후 Claude Code Opus 교차 리뷰를 완료했고, 로컬 MCP 설정의 E2E 유입을 추가로 차단했다. v1 당시의 인증 실패 기록은 위에 별도로 보존한다.

## 공모전 요구사항 대조

[심사·제출 증거 현황](contest-evidence.md)에 1008판 기준과 현재 산출물, 최신 공지·외부 원본 제출·독립 평가의 미확인 사항을 정리했다. 공개 코드 후보와 대회 제출 요건 충족을 구분한다.

## 공모전 후속 후보

[제출 후보 설명과 시연](contest-submission.md)에 근거 조회·수정·정책 공백 조사, 공정 비교·가림 평정의 재현 순서를 정리했다. 코드 준비와 live·독립 사람 평가·원본 제출 권한 확인을 구분한다. 개인 판정은 후순위이며 main 릴리스는 확정하지 않는다.
