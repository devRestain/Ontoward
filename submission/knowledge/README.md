# v5.0 실행 지식

[graph.py](graph.py)의 ClinicalKnowledge가 하나의 RDFLib Graph를 소유하고, [conditions.py](conditions.py)가 타입 값과 공개 점수 정책을 검증한다. 공유 Pattern·질환별 Association·Feature 조건·조건부 기여를 고정 인터페이스로 조회한다.

| 파일 | 역할 |
|---|---|
| schema.ttl | 현재 v5.0 구조; 준비용 schema와 같은 바이트 |
| scoring_policy.json | 버전이 있는 공개 순서형 점수 정책 |
| manifest.json | D15 수용 자산의 버전·경로·SHA-256과 승인 영수증 해시 |
| vocabulary.ttl·임상 .ttl | 별도 수용한 어휘·표현·Association |
| labels.ko.json·questions.ko.json | 해시 접두사가 붙은 한국어 표시 이름과 최소 질문 |
| plans JSON | 선택적인 질환별 계획·교육; 현재 배치에는 없음 |

manifest는 schema_version=5.0, registry_version, normalization_version, source_snapshots와 파일 해시, scoring_policy_version 및 정책 파일 해시를 고정한다. schema·vocabulary·하나 이상의 bundles와 선택 labels·questions·plans는 submission 기준 knowledge/ 내부 상대 경로만 사용한다.

prepare()는 모든 RDF 자산을 로드하고 타입·소유 관계·조건을 검증한 뒤 Association 점수와 atomic/joint FeatureContribution을 계산한다. 진료 중 환자 상태를 Graph에 쓰지 않는다. get_patterns_by_target와 get_disease_patterns는 Association ID와 적용 조건을, get_pattern_features는 타입 Feature를, get_feature_contributions는 기준·정교화 연관과 차분을 반환한다.

전체 원천 규모를 위해 검증된 profile·Feature·명칭·정교화 경로를 내부에서 인덱싱한다. 의미 없는 모든 조합의 비교 행렬은 유지하지 않으며 조회·점수 정책은 동일하다. preview_only manifest는 production reader가 거부하고 명시적 배치 승인을 거친 자산만 통합한다.

원천 변형은 모든 조건이 충족될 때 점수를 활성화한다. 더 구체적인 일치 표현은 점수가 낮아져도 기준 표현을 대체한다. 같은 Target은 한 번 집계하며 별개 에피소드를 섞지 않는다. zero·소수 값을 보존하고 source likelihood를 확률로 바꾸지 않는다.

labels는 기존 URI→한국어 표시 이름이며 Graph를 수정하지 않는다. questions는 URI→문구 사전이며 {symptom} 자리표시자를 사용하고 대상 URI|속성 URI 예외가 우선한다. 모든 치환 결과를 NFC 1–30자로 검증한다. plans는 질환 URI별 tests·treatment·disposition·follow_up과 education 목록이다. 승인 자산 밖의 질문이나 계획은 생성하지 않는다.

현재 사용자 승인 Association 9,400개와 96,017 triple, 증상 490개와 속성 16개의 질문, 257개 한국어 표시 이름을 수용했다. 원래 preview는 그대로 보존하며 실행이 부모 data/를 읽지 않는다. 실제 RDF와 합성 환자·모델 응답을 사용한 독립 ZIP 실행을 검증했다. ExamFinding·ContextFactor와 질환별 계획은 현재 배치에 없다. 사용자 수용을 독립 임상 검증이나 실제 Luna·공식 서버 수락으로 해석하지 않는다.

이 README는 ZIP에서 제외하며 코드·스키마·공개 정책과 별도 수용한 지식만 포함한다. 옛 v4.2 그래프와 준비 인터페이스는 실행 입력이 아니다.
