# 제출 지식과 RDFLib 접근

이 디렉터리는 제출용 RDFLib 코드와 실행에 필요한 온톨로지 자산을 함께 보관한다. graph.py의 ClinicalKnowledge가 하나의 Graph를 소유하고 고정 조회 인터페이스를 제공한다. manifest와 SHA-256을 검증하여 로드하고 후보·속성·Pattern·Feature·Context·진찰·검사 계획을 조회하는 코드가 구현되어 있다. 실제 승인 실행 자산은 아직 없다.

완성된 자산은 이 디렉터리 내부에 배치한다.

| 파일 | 역할 |
| --- | --- |
| graph.py / __init__.py | RDFLib 접근 Python 패키지 |
| manifest.json | 내부 자산 목록; 현재 없음 |
| schema.ttl / vocabulary.ttl | 필요한 RDF 스키마·기초 어휘 |
| 출처별 .ttl | 완성된 임상 관계 묶음 |
| questions.json | 속성·대상 URI별 준비 질문; 선택 자산 |
| plans.json | 질환 URI별 준비 계획·교육; 선택 자산 |
| 필요한 schema.json | JSON 구조 검증 스키마; RDF triple 입력과 구분 |

파일명은 배치 예시이며 없는 자산을 빈 파일로 만들지 않는다. manifest는 schema·vocabulary·하나 이상의 bundles와 선택적인 questions·plans를 선언한다. 각 항목은 path와 SHA-256을 가지며 path는 submission 기준 상대 경로(예: knowledge/schema.ttl)로 knowledge 디렉터리 안에 한정한다. 설정은 ../.env와 ../settings.py가 소유하며 기본 manifest 경로는 knowledge/manifest.json이다. 실행과 테스트는 제출 내부 파일을 사용한다.

Turtle은 RDFLib Graph의 데이터 입력이다. JSON Schema는 JSON 구조 검증이 필요한 경우 함께 사용하며, 단순히 Graph에 RDF 파일처럼 읽는 대상으로 취급하지 않는다. 현재 로더는 Pydantic으로 manifest와 계획을 검증한다. 질문 JSON은 URI→문구 사전이며 {symptom} 자리표시자만 치환한다. 계획 JSON은 질환 URI별 tests·treatment·disposition·follow_up 문자열과 education 문자열 목록이다. 없는 질문·관계·교육 내용은 생성하지 않는다.

이 안내 문서는 ZIP에서 제외하고 Python·Turtle·필요한 JSON 파일은 같은 상대 경로로 포함한다.
