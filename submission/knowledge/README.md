# v5.0 실행 지식과 D42 일반 호소 수용

ClinicalKnowledge는 하나의 읽기 전용 RDFLib Graph와 조회 색인을 소유한다. Disease→Association→공유 Pattern→Feature 표현은 v5.0이며 D17이 환자 관찰을 Pattern부터 평가한다.

D18·D20·D23의 기존 원천과 검증 문구를 보존하고 D42에서 일반 호소·한국어 표현·질문·기록 속성·로컬 DDXPlus metadata를 추가했다. 현재 manifest는 `admitted`이며 v5.0 구조, 843개 질환과 기존 9,401개 Association의 점수·조건을 유지한다. 현재 Association은 9,955개다. [현재 배치와 작성 안내](../../data/preparation/v5/common-complaints-2026-10-18-r2/README.md)는 원래 수용 영수증·D41 동결 ZIP과 구분한다. 추가 사용자·임상 승인 대기는 없다.

| 현재 파일 | 역할 |
|---|---|
| schema.ttl | v5.0 구조 계약 |
| scoring_policy.json·*-scoring_policy.json | 기존 원천 기준과 manifest에 고정한 현재 출처별 지지 정책 |
| *-reasoning_policy.json | manifest에 고정한 D17 제한 반증과 상한 |
| manifest.json | 현재 D42 그래프·문구·출처·정책·수용 영수증 해시와 admitted 상태 |
| *-vocabulary.ttl·*-clinical.ttl | 수용한 원천 표현·typed Context·ROS·필수 조건과 직접 진찰 경로 |
| *-questions.ko.json | 증상 518개·속성 계약 689개·Context 310개의 문진과 직접 문진 제외 15개 |
| Python reader | 타입·조건·점수·문구 검증과 읽기 전용 조회 |

새 admission에서는 manifest가 schema·vocabulary·임상 bundle·정책과 선택 labels/questions/plans의 경로·SHA-256을 고정해야 한다. preview_only와 철회된 manifest를 거부하며 부모 data/assets나 빈 Graph로 우회하지 않는다. 실제 발화는 준비와 전달 양쪽에서 NFC 1–30자로 검증한다.

D20의 그래프 전용 수용은 원천 의미·식별자·조건·관계 단말을 검증하고 문구 준비를 분리한다. 실제 prepare는 진찰 요청과 질문을 포함한 전체 검증을 사용한다. typed Context는 기존 SOAP 병력 필드와 양성 +1 상한으로 소비하고, inSystem은 주호소 계통을 고정하는 집중 ROS에만 사용한다. HAS_PREREQUISITE는 확인된 적용 조건으로 충족해야 원천 지지를 활성화한다.

현재 제출 ZIP은 manifest가 참조하는 지식 자산과 필수 실행 파일만 포함한다. D24에서 현재 manifest가 참조하지 않는 과거 D20 파일 세 개는 data의 원본과 해시가 같은 것을 확인한 뒤 실행 디렉터리에서 제거했다. 원래 그래프·승인 이력은 data 소유 경로에 보존한다. 한국어 문구는 생성 결과 그대로 전달하며 NFC 1–30자를 prepare와 전달 양쪽에서 확인한다.

원천 지지는 완전한 Feature·적용 조건이 맞을 때 활성화한다. 구체적인 매칭은 낮은 점수여도 조상을 대체하고 같은 Disease–Target은 한 번 집계한다. 다른 에피소드를 합치지 않는다. 질문은 Target 또는 대상|속성 키로 연결하며 원인 진단을 전제한 대상은 직접 문진을 차단한다. 원인 조건을 삭제한 질문의 긍정으로 원래 개념을 확정하지 않는다.

D42의 정성적 외부·작성자 연관은 정책 점수 1을 기본값으로 사용하고, 명시한 0–4 지지 수준은 작성자 판단으로 보존한다. 기존 SNOMED/BODHI가 같은 Association에 있으면 기존 선택 순서를 유지한다. source typicality·음성 감점·확률을 추정하지 않는다. `QuestionTemplate.units`는 등록한 숫자 형식이며 질환 임계값이 아니다. D41의 정규화·CanonicalSnapshot이 준비한 표현과 수치를 소비하고 원문을 SOAP에 우회 삽입하지 않는다.

새 후보의 자동 검사와 합성 상담 결과를 독립 임상 검증·실제 환자 성능·공식 서버 수락으로 일반화하지 않는다. 실행 승인 경계와 유지 중인 행동 검증은 [애플리케이션 상태](../PROJECT_STATE.md), 전체 생성 과정은 [생성 도구](../../Dev/ontology/README.md)가 기록한다.
