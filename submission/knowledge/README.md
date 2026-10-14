# v5.0 실행 지식

[graph.py](graph.py)의 ClinicalKnowledge가 하나의 RDFLib Graph를 소유하고, [conditions.py](conditions.py)가 타입 값과 공개 점수 정책을 검증한다. 공유 Pattern·질환별 Association·Feature 조건·조건부 기여를 고정 인터페이스로 조회한다.

| 파일 | 역할 |
|---|---|
| schema.ttl | 현재 v5.0 구조; 준비용 schema와 같은 바이트 |
| scoring_policy.json | 버전이 있는 공개 순서형 점수 정책 |
| manifest.json | 수용된 실행 자산의 버전·경로·SHA-256; 현재 임상 manifest 없음 |
| vocabulary.ttl·임상 .ttl | 별도 수용한 어휘·표현·Association |
| questions.json·plans.json | 선택적인 준비 문진·계획·교육 |

manifest는 schema_version=5.0, registry_version, normalization_version, source_snapshots와 파일 해시, scoring_policy_version 및 정책 파일 해시를 고정한다. schema·vocabulary·하나 이상의 bundles와 선택 questions·plans는 submission 기준 knowledge/ 내부 상대 경로만 사용한다.

prepare()는 모든 RDF 자산을 로드하고 타입·소유 관계·조건을 검증한 뒤 Association 점수와 atomic/joint FeatureContribution을 계산한다. 진료 중 환자 상태를 Graph에 쓰지 않는다. get_patterns_by_target와 get_disease_patterns는 Association ID와 적용 조건을, get_pattern_features는 타입 Feature를, get_feature_contributions는 기준·정교화 연관과 차분을 반환한다.

원천 변형은 모든 조건이 충족될 때 점수를 활성화한다. 더 구체적인 일치 표현은 점수가 낮아져도 기준 표현을 대체한다. 같은 Target은 한 번 집계하며 별개 에피소드를 섞지 않는다. zero·소수 값을 보존하고 source likelihood를 확률로 바꾸지 않는다.

questions는 URI→문구 사전이며 {symptom} 자리표시자를 사용한다. plans는 질환 URI별 tests·treatment·disposition·follow_up과 education 목록이다. 준비되지 않은 질문이나 계획은 생성하지 않는다.

현재 structural schema와 정책·코드는 포함되어 있으나 실제 임상 manifest·묶음·문진·교육 자산은 수용되지 않았다. data/preparation/v5/의 preview를 자동으로 사용하지 않으며 production prepare()는 누락 자산 오류로 멈춘다. 오프라인 검증은 임시 제출 복사본의 합성 자산을 사용한다.

이 README는 ZIP에서 제외하며 코드·스키마·공개 정책과 별도 수용한 지식만 포함한다. 옛 v4.2 그래프와 준비 인터페이스는 실행 입력이 아니다.
