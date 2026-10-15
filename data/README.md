# 지식 준비 자료

data/는 원천 식별·판본·파일 해시·매핑·검토와 지속 준비 결과를 소유한다. 원본 RF2·BODHI·주최자 패키지는 assets/에 그대로 보존하며 환자 상태와 실제 실행은 submission/이 소유한다.

| 경로 | 역할 |
|---|---|
| [ontology/](ontology/README.md) | 현재 v5.0 schema, starter vocabulary, 승인 용어 영수증 |
| [preparation/v5/](preparation/v5/README.md) | 전체 원천 SQLite·후보 RDF·검토 자료와 보존된 앞선 preview |
| [ontology/v4.2/](ontology/v4.2/schema.ttl) | 정확히 보존한 deprecated schema와 vocabulary |
| [ontology/deprecated.json](ontology/deprecated.json) | 이전 추출 인터페이스·도구·준비 자료의 deprecation 목록 |
| catalog/·provenance/ | 보존된 원본 탐색·공모전 출처 식별 |
| 이전 preparation/ 파일럿 | 원응답·검토·승인과 실행 증거; 현재 구축 입력과 분리 |

현재 준비는 공급된 International 2026-05-01 기반·Korean 2026-06-15 확장의 전체 Snapshot과 BODHI-S 8개 CSV를 수집한다. 원천·최신 행·정규화·RDF·주장·판단·승인은 SQLite가 보존하며 후보 RDF와 배치 검토 자료를 생성한다. 원천 기반 선택적 개발 Sol은 KST 예산과 공유 대장에서 제한한다. 실제 집계와 검증은 [데이터 상태](PROJECT_STATE.md)와 각 빌드의 report·verification에 기록한다.

각 preview는 schema·registry·정규화·Snapshot·파일 해시·점수 정책 버전을 고정한다. sources.json에 raw UUID·식별자·원천 조건·행 위치와 제외/보류 이유를, registry.json에 식별자 확인과 의미상 검토 상태를 유지한다. 한국어 description은 같은 SCTID의 명칭으로 연결한다.

BODHI의 두 방향 likelihood는 구분하고 원래의 zero와 소수 점수를 보존한다. strong_predictor를 추가 가산하거나 라벨을 확률로 해석하지 않는다. 원천의 조건 묶음을 합치거나 해결되지 않은 동반 소견을 삭제하지 않는다.

preview_only와 registry candidate는 사람의 매핑·임상 검토와 제출 자산 수용 이전 상태다. 필요한 실행 자산을 별도 수용한 뒤 submission/knowledge/에 배치한다. 런타임과 그 테스트는 이 data/ 디렉터리에 의존하지 않는다.

D15의 [별도 승인 영수증](preparation/v5/full-snomed-bodhi-2026-10-15/review-approved.json)은 전체 후보 사용에 대한 사용자 수용을 기록한다. [admission.json](preparation/v5/full-snomed-bodhi-2026-10-15/admission.json)은 제출 지식 수용 결과이며 원래 preview와 미승인 검토 양식은 보존한다. [최소 한국어 문구](preparation/v5/full-snomed-bodhi-2026-10-15/texts/preparation.json)는 라벨·질문 해시를 같은 승인에 고정한다. 독립 임상 검증·질환별 계획·실제 모델 성능과 구분한다.

승인된 510개 영어 용어 목록과 영수증은 유지한다. 이전 문헌 파일럿의 원응답·승인도 보존하며 새 데이터로 자동 변환하거나 작업을 재개하지 않는다. 계약은 [D08/D09](../DECISION_STATE.md#D08), 도구는 [Dev 안내](../Dev/ontology/README.md), 운영 기록은 [PROJECT_STATE](PROJECT_STATE.md)를 따른다.
