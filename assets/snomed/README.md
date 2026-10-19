# SNOMED CT 원본

사용 허가를 받은 International 2026-05-01과 Korean 2026-06-15 RF2 Snapshot 원본을 보관한다. 파일·릴리스 메타데이터·라이선스는 변경하지 않고 자동 다운로드하지 않는다.

Korean 확장은 Module Dependency가 선언한 International 기반 모듈 20260501과 함께 사용한다. 최신 component 행과 활성 여부를 확인하고 영어·한국어 명칭을 같은 SCTID에 연결한다. Korean 고유 개념은 확장 모듈의 출처를 유지한다.

D49의 새 준비는 [Extraction](../../Extraction/README.md)이 수행하며 입력 해시·배포 의존성·chunk cursor와 새 결과를 data/extraction/v5-enum/에 기록한다. 과거 data/preparation/v5/ custody는 보존하지만 새 builder 입력으로 재사용하지 않는다. 원본은 제출 ZIP에 포함하지 않는다. 식별자 존재 확인과 임상 의미 검토·실행 자산 수용은 별도로 진행한다.
