# 원자료·철회·새 빌드 결과

data/는 원천 식별·해시·지속 준비 결과·체크포인트·artifact 증빙을 소유한다. 원본은 assets/에 그대로 보존하며 실제 환자 facts는 submission/이 소유한다.

D49에서 기존 임상 DB의 **활성 사용을 철회**했다. 과거 원자료·source-custody SQLite·준비 결과·수용 ZIP과 작은 과거 증빙은 보존한다. 추출 전용 원본 로그·체크포인트는 사용자 요청으로 삭제했다. 제출 경로의 옛 생성 RDF·질문·정책과 점수 전용 생성기는 철회한 뒤 보관했으며, 새 실제 번들의 설치 완료 후 사용자 요청으로 해당 압축본을 삭제했다. [withdrawal.json](extraction/retired-d42-2026-10-19/withdrawal.json)은 파일·archive 신원을 기록한다. 과거 D20–D48 수용은 역사적 증거이며 새 빌드의 입력·승인·기본 policy가 아니다.

| 경로 | 역할 |
|---|---|
| [ontology/](ontology/README.md) | 작성된 v5.0 / v5-enum-1 구조 계약 |
| extraction/v5-enum/work/ | 완료 후 보관 해제로 현재 비어 있음; 과거 체크포인트 재개 불가 |
| extraction/v5-enum/output/ | 설치본과 중복된 staging 정리 후 현재 비어 있음 |
| extraction/retired-d42-2026-10-19/ | 압축본 삭제 후 철회 영수증만 보존 |
| preparation/·catalog/ | 보존된 과거 원천 custody·준비·수용 결과 |
| provenance/ | 수행한 검증·소스·이미지·임시 artifact 신원 |

fresh 추출은 [Extraction](../Extraction/README.md)의 네 원자료 경로에서 빈 작업 DB로 시작한다. 이전 생성 데이터·질문·어휘·source-custody SQLite와 Astra snapshot/정책을 fresh 정본으로 읽지 않는다. 별도 D58 augmentation만 최신 활성 strict 번들을 부모로 사용한다. 한 fingerprint에는 공급자 하나만 사용하고 완료·neutral을 재호출하지 않는다. API/CLI 불명 전송은 운영자의 명시적 재시도 전까지 멈춘다.

현재 활성 번들은 최신 부모 `1bcaba1dffb744c468bb191df3267dad`를 보완한 D58 child `cec62f4596bedd9b9488aa75e3d38f04`다. 개념 11개·실행 관계 9개·질문 6개를 추가하고 허용 부모 관계 4개를 변경했다. 실제 API 생성은 7회이며 [생성·보존·활성화 결과](provenance/augmentation-d58-2026-10-21.json)에 usage와 수행한 검증을 남겼다. 사용자 요청으로 이번 작업의 체크포인트·중복 DB/번들·임시 파일 518개(210.27 MiB)를 삭제하고 [정확한 삭제·보호 hash 명세](provenance/augmentation-d58-cleanup-2026-10-21.json)와 [typed delta·URI mapping](provenance/augmentation-d58-delta-2026-10-21.json)을 보존한다. 활성 번들과 기존 부모는 남으며 삭제한 plan·SQLite·원래 요청/응답은 재개할 수 없다. 실제 모델 상담 정확도·임상·공식 평가는 미실행이다.

실행 RDF와 임상 입력에는 점수·가중치·관계 출처·confidence·reviewer를 넣지 않는다. 실제 환자 취득 source/turn과 Education 문서 경로/hash/인용은 각 실행 책임에서 보존한다. 라이선스·원자료 역할은 [DATA_USE.md](../Extraction/DATA_USE.md)에 분리한다.

D49 초기 구현과 D50 수용은 기존 provenance에 과거 증빙으로 보존합니다. 실제 빌드 `87e8b4c54b0689453cea91b3bb316290`는 추출·컴파일·검증·로컬 설치를 완료했습니다. 완료 후 여섯 작업 DB와 로그·중복 출력·추출 임시 기록을 삭제했고, [최종 감사 기록](provenance/extraction-final-audit-2026-10-21.json)에 설정·사용량 요약·수동 교정 내역을, [삭제 영수증](provenance/extraction-storage-cleanup-2026-10-21.json)에 정확한 삭제 경로·용량과 설치본 보존 검증을 남겼습니다. 원래 요청 본문·응답·재시도 이력과 체크포인트는 더 이상 보관하지 않습니다.

## 저장 구조를 읽는 순서

| 구분 | 정의와 열람 경로 | 주의할 점 |
|---|---|---|
| 새 작업 DB | [7테이블·전체 열·키](../Test/atlas.html#sqlite), [jobs.py](../Extraction/ontoward_extraction/jobs.py) | 생성기 전용. 요청–job 연결은 JSON이며 SQL FK가 아닙니다. |
| 새 실행 지식 | [14클래스·23속성 RDF](../Test/atlas.html#rdf), [온톨로지 안내](ontology/README.md) | 실제 설치 전 인스턴스 수를 주장하지 않습니다. |
| manifest와 부속 JSON | [6파일·질문·지침 계약](../Test/atlas.html#bundle) | 경로·hash 검증과 manifest 마지막 교체가 필요합니다. |
| 환자 상태 | [CaseFact·Assessment 스키마](../Test/atlas.html#facts) | data/ DB에 저장하는 지식이 아니라 증례 메모리입니다. |
| 과거 custody와 결과 | preparation/·catalog/·retired-d42/·provenance/ | 보존된 이력입니다. 새 추출 입력이나 runtime fallback으로 사용하지 않습니다. |

설치 지식의 manifest·다섯 자산 해시·prepare·coverage는 체크포인트 삭제 전후 모두 통과했습니다. 해당 실제 번들로 대표 상담을 검증하는 작업은 별도로 남아 있으며, 임상적 타당성과 공식 평가를 완료했다고 주장하지 않습니다. 합성 번들과 ZIP은 계속 Tmp/에서만 사용합니다.
