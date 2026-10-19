# 원자료·철회·새 빌드 결과

data/는 원천 식별·해시·지속 준비 결과·체크포인트·artifact 증빙을 소유한다. 원본은 assets/에 그대로 보존하며 실제 환자 facts는 submission/이 소유한다.

D49에서 기존 임상 DB의 **활성 사용을 철회**했다. 과거 원자료·source-custody SQLite·준비 결과·수용 ZIP·기존 증거는 보존한다. 제출 경로의 옛 생성 RDF·질문·정책과 점수 전용 생성기는 [보관 디렉터리](extraction/retired-d42-2026-10-19/)에 원본 bytes와 해시를 남겼다. [withdrawal.json](extraction/retired-d42-2026-10-19/withdrawal.json)은 파일·archive 신원을 기록한다. 과거 D20–D48 수용은 역사적 증거이며 새 빌드의 입력·승인·기본 policy가 아니다.

| 경로 | 역할 |
|---|---|
| [ontology/](ontology/README.md) | 작성된 v5.0 / v5-enum-1 구조 계약 |
| extraction/v5-enum/work/RUN_ID/ | 입력·설정 fingerprint, SQLite job/요청/응답/사용량, worker lock |
| extraction/v5-enum/output/RUN_ID/ | 여섯 파일의 새 staging 번들 |
| extraction/retired-d42-2026-10-19/ | 철회 runtime·builder 보관본과 검증 해시 |
| preparation/·catalog/ | 보존된 과거 원천 custody·준비·수용 결과 |
| provenance/ | 수행한 검증·소스·이미지·임시 artifact 신원 |

새 추출은 [Extraction](../Extraction/README.md)의 네 원자료 경로에서 빈 작업 DB로 시작한다. 이전 생성 데이터·질문·어휘·source-custody SQLite와 Astra snapshot/정책을 새 정본으로 읽지 않는다. 한 fingerprint에는 공급자 하나만 사용하고 완료·neutral을 재호출하지 않는다. API/CLI 불명 전송은 운영자의 명시적 재시도 전까지 멈춘다.

실행 RDF와 임상 입력에는 점수·가중치·관계 출처·confidence·reviewer를 넣지 않는다. 실제 환자 취득 source/turn과 Education 문서 경로/hash/인용은 각 실행 책임에서 보존한다. 라이선스·원자료 역할은 [DATA_USE.md](../Extraction/DATA_USE.md)에 분리한다.

D49의 초기 구현 수용은 [증빙](provenance/algorithm-d49-2026-10-19.json), D50의 진료 수용은 [D50 provenance](provenance/algorithm-d50-2026-10-20.json)에 보존합니다. 이후 별도로 승인된 실제 NOVA 빌드 `10282b2e382f085d756e9f6645dc05fe`는 진행 중입니다. 2026-10-20 01:33 KST 읽기 전용 조회에서는 normalize 단계였고 실제 활성 manifest는 없었습니다. 최신 작업·요청 상태는 [데이터 상태](PROJECT_STATE.md)와 체크포인트를 따릅니다. 이전 수용의 not_run은 해당 과거 작업 범위에만 적용합니다.

## 저장 구조를 읽는 순서

| 구분 | 정의와 열람 경로 | 주의할 점 |
|---|---|---|
| 새 작업 DB | [7테이블·전체 열·키](../Test/atlas.html#sqlite), [jobs.py](../Extraction/ontoward_extraction/jobs.py) | 생성기 전용. 요청–job 연결은 JSON이며 SQL FK가 아닙니다. |
| 새 실행 지식 | [14클래스·23속성 RDF](../Test/atlas.html#rdf), [온톨로지 안내](ontology/README.md) | 실제 설치 전 인스턴스 수를 주장하지 않습니다. |
| manifest와 부속 JSON | [6파일·질문·지침 계약](../Test/atlas.html#bundle) | 경로·hash 검증과 manifest 마지막 교체가 필요합니다. |
| 환자 상태 | [CaseFact·Assessment 스키마](../Test/atlas.html#facts) | data/ DB에 저장하는 지식이 아니라 증례 메모리입니다. |
| 과거 custody와 결과 | preparation/·catalog/·retired-d42/·provenance/ | 보존된 이력입니다. 새 추출 입력이나 runtime fallback으로 사용하지 않습니다. |

실제 생성 완료, 검증된 번들 설치, 그 번들로 대표 상담 수용이 남아 있습니다. 이번 문서 작업은 체크포인트를 읽기 전용으로 확인했으며 worker·요청·수용 결과·이전 영수증을 변경하지 않았습니다. 합성 번들과 ZIP은 계속 Tmp/에만 둡니다.
