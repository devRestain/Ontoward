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

이번 D49 결과는 [증빙](provenance/algorithm-d49-2026-10-19.json)과 [상태](PROJECT_STATE.md)를 따른다. 실제 모델 DB 생성과 실제 설치는 not_run이며 활성 manifest는 없다. 합성 데이터와 ZIP은 Tmp/에만 존재한다. 다음 작업은 인증을 마친 선택 공급자로 실제 DB를 생성·검증·설치하는 것이다.
