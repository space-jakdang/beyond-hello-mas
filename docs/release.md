# 제출 재현 기록

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

## 미완료 검증

실제 OpenAI 평가/모델 스냅샷/가격 검증, 독립 사람 정답과 적합성 평가, 간접 위기 표현 검출 목표는 미완료입니다. Claude 교차 리뷰는 OAuth 인증 만료로 실행하지 못했습니다. 이후 PR은 사용자 진행 지시에 따라 자체 Ponytail 검토와 테스트 결과로 통합했으며 교차 리뷰 통과로 기록하지 않습니다. develop → main 제출 PR은 이 한계를 명시하고 별도로 준비합니다.

## 깨끗한 clone 검증 결과

2026-10-18 문서·보고서 커밋 `e08ee64`를 `git clone --no-local`로 새 임시 디렉터리에 복제했습니다. 기존 venv/node_modules/.env/runtime/로컬 계획을 가져오지 않고 잠금 파일로 설치했습니다. 패키지 다운로드 캐시와 OS의 Chromium 설치 캐시는 재사용했으므로 완전히 별도 컴퓨터를 시험한 것은 아닙니다.

- `make install`, `make sample`, Chromium 설치 성공.
- `make check`: Python 64 passed / private MCP 2 skipped, TypeScript/Vite build 성공, 브라우저 E2E 5 passed, HEAD 공개 검사 통과.
- `make eval`: 공개 입력 40건을 유지한 partial 보고서, 완료24/실패16, 예상 종료 코드 2. 명시적 척도의 private MCP 미설정 때문에 실패하며 누락을 성공으로 처리하지 않음.
- 공개 Markdown 로컬 링크 누락 0건. 최종 보고서에 개인 로컬 경로/키 없음. 고정 평가 코드와 제출 코드의 기능 diff 없음.

이 기록 추가는 문서만 변경합니다. 최종 PR CI로 공개 파일 검사와 전체 테스트를 다시 확인합니다.
