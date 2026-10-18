# 행정동 경계

[통계청 SGIS](https://sgis.kostat.go.kr)의 공공누리 제1유형 경계를 가공한 [vuski/admdongkor](https://github.com/vuski/admdongkor) 자료(CC BY 4.0)입니다. 배포 조건은 [LICENSE-DATA](LICENSE-DATA)에 보존합니다. 원본 commit, SHA256, 가져온 URL은 [manifest.json](manifest.json)에 있습니다.

2025-07-01 버전에서 강남구/춘천시 47개 읍면동만 선택하고 속성을 정리했습니다. 좌표는 변경하지 않았습니다. WGS84 경위도(EPSG:4326), SGIS 통계동 8자리 코드입니다. 행안부 법정동 코드와 혼용하지 않습니다. `uv run python -m scripts.import_boundaries`로 같은 고정 원본에서 재생성합니다.

로컬 분석은 코드와 동 이름이 모두 일치할 때만 경계를 연결합니다. 불일치는 coverage에 남기고 임의 추정하지 않습니다. 2025-07 기준 경계를 모든 분석월에 공통 사용하므로 이후 분동/경계 변경이 있는 입력에는 맞지 않을 수 있습니다. 자료 정확성은 원 배포자도 보증하지 않습니다. 공개 sample의 합성 코드는 이 경계에 연결하지 않습니다.
