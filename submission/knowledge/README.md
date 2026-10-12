# 제출 지식과 RDFLib 접근

이 디렉터리는 제출용 RDFLib 코드와 실행에 필요한 온톨로지 자산을 함께 보관한다. graph.py의 ClinicalKnowledge가 하나의 Graph를 소유하고 고정 조회 인터페이스를 제공한다. 실제 로딩·조회는 현재 미구현이다.

완성된 자산은 이 디렉터리 내부에 배치한다.

| 파일 | 역할 |
| --- | --- |
| graph.py / __init__.py | RDFLib 접근 Python 패키지 |
| manifest.json | 내부 자산 목록; 현재 없음 |
| schema.ttl / vocabulary.ttl | 필요한 RDF 스키마·기초 어휘 |
| 출처별 .ttl | 완성된 임상 관계 묶음 |
| 필요한 schema.json | JSON 구조 검증 스키마; RDF triple 입력과 구분 |

파일명은 배치 예시이며 없는 자산을 빈 파일로 만들지 않는다. manifest의 자산 경로는 manifest 위치 기준 상대 경로로 두고 knowledge 디렉터리 안에 한정한다. 설정은 ../.env와 ../settings.py가 소유하며 기본 manifest 경로는 knowledge/manifest.json이다. 실행과 테스트는 제출 내부 파일을 사용한다.

Turtle은 RDFLib Graph의 데이터 입력이다. JSON Schema는 JSON 구조 검증이 필요한 경우 함께 사용하며, 단순히 Graph에 RDF 파일처럼 읽는 대상으로 취급하지 않는다. 구체적인 manifest와 JSON 검증 계약은 로더 구현 때 확정한다.

이 안내 문서는 ZIP에서 제외하고 Python·Turtle·필요한 JSON 파일은 같은 상대 경로로 포함한다.
