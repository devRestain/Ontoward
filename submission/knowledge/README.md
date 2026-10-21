# 실행 지식 계약

D49의 새 실제 번들 `87e8b4c54b0689453cea91b3bb316290`를 로컬 설치했다. **manifest·다섯 asset 해시·loader·coverage와 변경 없는 run.py의 prepare를 검증**했다. [설치 증빙](../../data/provenance/extraction-installed-2026-10-21.json)을 따르며 실제 번들 대표 상담·임상·공식 평가와 정식 ZIP은 별도다. 합성 번들은 Tmp/에서만 로드한다. 과거 clinical/vocabulary/questions/scoring/reasoning 자산은 활성 경로에서 철회했고 [철회 영수증](../../data/extraction/retired-d42-2026-10-19/withdrawal.json)에 보존했다.

ClinicalKnowledge.load는 `schema_version=5.0`, `knowledge_contract=v5-enum-1`, build_id와 다섯 asset의 상대 경로/SHA-256을 검증한다. 각 경로는 manifest 디렉터리를 기준으로 해석하며 절대 경로·상위 이탈·symlink 이탈·hash 불일치를 거절한다. 이전 manifest의 status·receipt·policy와 호환 변환은 없다.

[아틀라스의 RDF 지도](../../Test/atlas.html#rdf)에서 클래스·관계·카디널리티를, [번들/JSON 지도](../../Test/atlas.html#bundle)에서 questions·attribute_roles·guidelines·manifest의 필드를 함께 읽을 수 있습니다. 질문은 실행 문구와 답변 계약, RDF는 일반 임상 조건, CaseFact는 실제 환자 관측을 각각 표현합니다. 서로 다른 역할을 하나의 DB로 혼동하지 않는 것이 출발점입니다.

| 번들 파일 | 내용 |
|---|---|
| schema.ttl | v5.0 구조 |
| vocabulary.ttl | 영어·한국어 표제/별칭, 역할·속성·허용 값·계통·진찰 경로 |
| clinical.ttl | Disease→Association→Pattern→Feature, effect·targetScope·applicability |
| questions.ko.json | questions와 attribute_roles; 구체 실행 시점·질문/단위·순서/기록 category/clarification |
| guideline-index.json | 새 Disease 전체의 selections; 빈 목록 허용 |
| manifest.json | 위 다섯 파일의 상대 경로·SHA-256과 build 신원 |

support·strong_support·against·strong_against는 전체 Pattern과 applicability가 맞을 때만 활성화한다. neutral은 작업 DB 완료 상태로만 남고 RDF에 출력하지 않는다. 부분 일치와 불일치는 활성 effect가 아니며 수치 점수·source-required 메타데이터·supporting-context 우회 경로를 사용하지 않는다. Condition의 수치·단위·구간 비교와 실제 CaseFact 취득 기록은 유지한다.

ContextFactor는 Target과 applicability에서 같은 CaseFact를 사용한다. 주체·가족 구성원·시점·관찰·episode를 보존하며 any 규칙과 질문의 구체 시점을 구별한다. 속성만 있는 Pattern도 존재 질문을 먼저 제공한다. attribute_roles가 질문 순서·SOAP category·clarification을 정하며 URI localname에 의존하지 않는다.

설치는 검증된 build 전용 파일 뒤 manifest를 원자적으로 교체한다. 상담은 읽기 전용 Graph 하나를 준비하고 부모 data나 원자료 DB를 읽지 않는다. 원문 지침은 지정 마운트에서 경로/hash/인용을 검증하며 ZIP에 넣지 않는다. 빈 selections는 명시적 model-knowledge Education에 사용한다. 생성·검증·설치 명령은 [Extraction](../../Extraction/README.md)을 따른다.

다섯 asset은 서로 다른 파일이어야 한다. any 규칙에는 구체 질문 scope가 필요하다. 물리적 EXAM은 환자의 current 시점에만 실행하며 컴파일러가 진찰 문구와 current 질문 자산을 함께 만든다. 가족·과거 사실도 등록 scope가 맞으면 같은 관찰 단위에서 매칭하지만 다른 사람의 현재 진찰로 대신하지 않는다.
