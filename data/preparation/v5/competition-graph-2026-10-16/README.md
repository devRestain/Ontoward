# 공모전 MVP 연결 그래프

이 배치는 D20에서 사용자가 선택한 공모전용 후보 그래프다. 기존 원천 DB와 D19 전체 카탈로그를 보존하면서, 소비 코드가 사용하는 ROS·Context·필수 조건을 원천 관계에 연결한다. 한국어 표현 생성은 별도 세션의 작업이다.

| 파일 | 용도 |
|---|---|
| ontology.sqlite3 | 새 그래프·원천 주장·승인 대장. 원천 행과 RF2 표현은 source_custody가 지정한 기존 DB를 읽기 전용으로 공유 |
| connections.json | 관계별 수, Context 유형, 지원 계통, 진찰 승격 범위와 기술적 제외 사유 |
| connection-evidence.json | 각 inSystem·contextType·hasSupportingContext 연결의 원천 행·경로 |
| review-approved.json | 정확한 build·후보 집합·파생 정책·Association·어휘에 대한 사용자 공모전 후보 수용 |
| admission.json | submission 내부 수용 결과와 독립 프로세스 그래프 로드 측정 |
| preview/ | 동일 그래프의 재현 가능한 RDF와 정본 SQLite 감사 참조 |
| required-text-assets.json | 한국어 세션에서 처리할 실제 Target·Context·Attribute·ExamMethod 의존 항목 |
| verification.json | 실제 수용 RDF의 원천 해시·소비 코드·세 가지 전체 오프라인 상담 검증 |
| case-present.json·case-absent.json·case-unknown.json | 영어 원천명 기반 테스트 문구와 스크립트 응답으로 실행한 합성 환자 상태 |
| packaging.json | 최종 로컬 ZIP의 파일·크기·해시와 독립 추출 그래프 확인 |

`contextType`은 기존 열 가지 범주를 사용한다. BODHI Context 식별자와 SCTID 동일성을 분리하며, 원천의 역할과 표현을 보존한다. 양성·0이 아닌 방향성 영향만 supporting Context에 연결하고 확인된 해당 주체의 존재에 질환별 최대 +1을 적용한다. HAS_PREREQUISITE는 Association의 공동 적용 조건이다. 원천 조건과 문진 의미를 충족하지 못한 항목에는 기술적 제외 사유를 남기며 추가 승인 결정을 기다리는 것으로 표시하지 않는다.

`inSystem`은 RF2 Finding site 또는 완전한 Pattern의 Location 값에서 명명된 구체적 기관 계통으로 이어지는 실제 is-a 경로다. 전체 신체와 기관계 하위 구분 노드는 제외한다. 이 연결은 집중 ROS의 주호소 계통 합집합에만 사용하고 질환 후보 검색을 제한하지 않는다.

한국어 세션은 `required-text-assets.json`의 build와 [승인 영수증](review-approved.json)을 기준으로 실제 문진·속성 질문·진찰 요청을 준비한다. 새 범위의 작업 집합과 호출 예산을 다시 고정하며 기존 D19 호출 상한을 그대로 재사용하지 않는다. 수용 영수증의 `text_assets`는 questions·labels·exam_requests별 JSON 경로와 SHA-256을 고정한다. exam_requests는 승인된 ExamMethod 식별자를 1–30 NFC codepoints 요청문으로 연결하며 admission이 RDF의 examRequestText로 반영한다. 질문과 명칭은 기존 런타임 JSON 계약을 사용한다.

D20 수용 당시 submission manifest는 `graph_admitted_text_pending`이었으며 이 디렉터리의 admission·검증·ZIP 보고서는 그 시점을 보존한다. 이후 D23에서 D22의 한국어 환자 행동을 수용해 현재 manifest는 `admitted`다. 새 영수증과 한국어 상담·독립 ZIP 결과는 [런타임 수용 결과](../runtime-text-2026-10-16/README.md)에 분리한다. 영어 테스트 문구는 과거 검증용이며 submission에 수용하지 않는다.

공식 환경 E2E·실제 Gateway 모델·공식 제출·평가는 이번 검증에 포함하지 않는다. 로컬 ZIP도 현재의 그래프·문구 상태를 그대로 보존하는 인계 산출물이다. 현재 결과와 다음 작업은 [데이터 상태](../../../PROJECT_STATE.md), 선택은 [D20](../../../../DECISION_STATE.md#D20), 재현 명령은 [생성 도구](../../../../Dev/ontology/README.md)가 소유한다.
