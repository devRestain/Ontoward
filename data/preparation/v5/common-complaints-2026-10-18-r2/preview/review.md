# v5.0 전체 원천 배치 검토

- 빌드: `6501f157bde1e2c367f4e7adc0266578c858d97eb3855de6981a4f31b682b2b7`
- 후보 집합 SHA-256: `4eee91447c4a2bea2e0b58d37eaf7abe2260d4929f1feb13f9466285417900ea`
- Association 후보: 9,955
- Registry 항목: 2,891

이 파일과 review-batch.json은 승인 요청 자료다. approved=false이며 자동 승인하지 않는다.

검토 대상은 식별자와 임상 역할, 변형의 모든 조건, 관계 그룹, 두 방향 likelihood와 충돌, 모델 정규화 후보다.
보류된 연결 소견·단위·역할·진찰 방법은 실행 자산에 포함하지 않는다.

## 원천별 처리

| 입력 | 행 수 |
|---|---:|

## 증상 변형 처리

| 결과 | 수 |
|---|---:|

상세 원천 행·정규화·판단은 ontology.sqlite3의 source_rows, normalizations, dispositions, source_assertions에서 확인한다.
sources.json은 정본 SQLite 감사 테이블과 입력 해시를 가리키며, registry.json은 매핑과 명칭을, target-roles.json은 전체 발견 역할을 담는다.
disease-target-coverage.csv는 질환과 Target별 연관 수를 제공한다. source_assertions와 normalizations에서 선택 평가·정규화 규칙·예외를 대조한다.
승인 시 approved_associations와 approved_registry에 실제 승인한 항목을 지정하고 required_rules를 검토한다.
임상 문진·진찰 요청·치료·교육 문구 작성과 실제 진단 성능 검증은 이 배치에 포함하지 않는다.
