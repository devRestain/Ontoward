# 임시 출력

`codex/`는 현재 Codex 작업의 임시 출력, `packaging/`는 생성 ZIP의 출력 디렉터리다. 두 디렉터리는 현재 비어 있다.

작업이 끝난 임시 파일과 압축물은 제거한다. 과거 소스 사본·계약·실행 이력의 보관소로 사용하지 않는다. 인증은 이 디렉터리 밖의 전용 Docker volume에 둔다.

도구는 [Dev](../Dev/README.md), 입력 자료는 [data](../data/README.md), 현재 운영 사실은 [루트 상태](../PROJECT_STATE.md)가 관리한다.
