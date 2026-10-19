# 무점수 v5.0 지식 구조

[schema.ttl](schema.ttl)은 D49의 `schema_version=5.0`, `knowledge_contract=v5-enum-1` 구조다. 실행 copy는 submission/knowledge/schema.ttl이며 실제 manifest는 새 번들 설치 전까지 없다. 과거 점수·source-required·admission 정책은 활성 계약에서 철회했다.

한눈에 구조를 보려면 [아틀라스의 RDF 스키마](../../Test/atlas.html#rdf)를 먼저 읽어 보세요. 현재 작성 스키마의 **14클래스·23속성·130 triples**를 도식·카디널리티·필드 표로 설명합니다. 이는 구조 정의의 수이며 실제 설치된 질환·패턴 개수가 아닙니다. [번들·질문 JSON](../../Test/atlas.html#bundle), [환자 사실](../../Test/atlas.html#facts), [추출 SQLite](../../Test/atlas.html#sqlite)는 별도 스키마로 연결해 두었습니다.

Disease → DiseasePatternAssociation → ClinicalPattern → ClinicalFeature를 유지한다. Pattern Target은 Symptom·ExamFinding·ContextFactor 중 하나이며 Feature는 그 Pattern의 Target을 상속한다. Association은 명시적 targetScope·applicability·diagnosticEffect를 가진다. effect는 support·strong_support·against·strong_against이며 neutral은 작업 DB의 완료 결과로만 남는다.

관계 동일성은 질환·Target/전체 Feature·scope·applicability로 정하고 effect를 제외한다. 같은 의미의 상충 effect는 최종 분류가 하나로 확정한다. 부분 Feature 일치는 활성 지지가 아니고 불일치를 반대 효과로 뒤집지 않는다. 전체 조건과 applicability가 확인되어야 등록 effect를 활성화한다. 명시적 모순으로 불가능해진 관계의 남은 조건은 질문하지 않는다.

환자·가족 구성원·시점·관찰·episode를 지키며 Context도 같은 사실 정본으로 매칭한다. 가족 구성원 한 명의 음성을 전체 가족 부재로 일반화하지 않는다. any는 규칙의 시간 범위이며 질문 자산은 current·past·unspecified를 확정한다. 같은 Target·scope의 존재 확인이 속성 질문보다 앞선다.

ExpectedValue는 concept·concept_set·quantity·interval이며 any_of/all_of·비교 연산자·단위·구간 경계를 보존한다. ValueMatch는 등록된 방향성 값 비교 경로다. 수치 진단 점수를 없애도 나이·실측값·기간·통증 척도·값 비교는 유지한다.

질문 JSON은 questions와 attribute_roles를 가지며 역할별 순서·SOAP category·clarification을 명시한다. 한·영 표제와 별칭은 vocabulary에서 제공한다. 실제 질문과 단일 EXAM 요청은 NFC 한국어 1–30 codepoint로 검증한다. Test는 검사 계획 역할이고 예선 TEST 행동을 만들지 않는다.

새 manifest는 build_id와 schema·vocabulary·clinical·questions·guidelines의 상대 경로·SHA-256만 가진다. 경로 이탈·hash 불일치·옛 형식을 거절한다. 빈 guideline selections는 모델 지식 교육으로 이어지고, 원문 선택은 경로·hash·인용 검증을 유지한다. 새 생성기와 공급자·중단/재개는 [Extraction 안내](../../Extraction/README.md), 과거 보존과 실제 상태는 [데이터 안내](../README.md)를 따른다.
