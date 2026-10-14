# NOVA 2026 공모전 참고 문서

이 README는 사람이 공모전 정보를 찾기 위한 안내다. 공식 사이트의 공개 페이지와 이미 받은 SDK·예제 파일을 바탕으로 정리했으며, 본문의 기술 문서는 에이전트가 소비할 수 있도록 영어로 작성했다. 에이전트의 읽기 순서와 문서 사용 규칙은 [AGENTS.md](AGENTS.md)에 있다.

| 찾는 정보 | 문서 |
| --- | --- |
| 공모전 목적·참가 조건·일정·예선과 본선의 차이 | [COMPETITION.md](COMPETITION.md) |
| 실행 자원·시간·의존성·코드 ZIP·본선 모델과 발표 자료 | [EXECUTION_AND_SUBMISSION.md](EXECUTION_AND_SUBMISSION.md) |
| 세션·행동 API·30자와 50턴 제한·SOAP 필드·오류 처리 | [API_AND_RECORD.md](API_AND_RECORD.md) |
| 평가 항목·배점·샘플과 공식 평가·최종 순위 | [EVALUATION.md](EVALUATION.md) |
| 제공 자료·지침 경로·공개 ZIP 해시·라이선스 확인 | [DATA_AND_ASSETS.md](DATA_AND_ASSETS.md) |
| 로그인·개발 키·크레딧·공개 운영 상태·문의 | [OPERATIONS.md](OPERATIONS.md) |
| 확인한 URL·출처·확인 범위·아직 알 수 없는 정보 | [SOURCES.md](SOURCES.md) |

홈·규칙·개발·평가·Q&A·서비스 상태·주 리더보드 페이지의 현재 확인일은 **2026년 10월 14일, 한국 시간**이다. 상태 페이지는 네 서비스를 이용 가능으로 표시하고 주 리더보드에는 점수가 있는 24팀이 표시된다. 이는 Ontoward의 실제 로그인이나 평가 성공의 증거가 아니다. 개발·제출 페이지의 로그인 전환과 별도 단계 쿼리 리더보드의 결과 부재는 10월 11일 관찰로 유지하며 다시 확인하지 않았다. 계정 내부 화면, 실제 키·현재 잔액·잔여 횟수·샘플 UUID, API 동작 여부도 확인하지 않았다.

이 폴더는 프로젝트에서 새로 만든 공모전 참고 자료다. 원본 임상 자료, 검색 코퍼스, 제출물에 포함되는 자료와는 역할이 다르다. 제공 자료 자체의 구조는 [상위 Architecture.md](../Architecture.md), 프로젝트 요구사항과 결정은 [PRD](../../PRD.md)와 [DECISION_STATE](../../DECISION_STATE.md)에서 확인할 수 있다.

원문은 [NOVA 공식 사이트](https://nova.snubhai.org/), [규칙](https://nova.snubhai.org/rules/), [개발 문서](https://nova.snubhai.org/docs/), [평가 안내](https://nova.snubhai.org/evaluation/)에 있다. 이 정리는 로그인, API 실행, 자료 다운로드, 업로드 또는 공식 평가를 수행한 기록이 아니다.

## 10월 14일 규칙 갱신과 발표 자료

현재 적용 규칙은 [10월 14일 업데이트](CHANGES_2026-10-14.md)에서 확인한다. 예선 Doctor는 10월 13일부터 `openai/gpt-6-luna`이며 사용자 확인에 따라 D01의 선택도 갱신했다. 개발 샘플 세션 100/일, 제출 후 샘플 검증 10/일, 세션 밖 Luna 성공 호출 1,000/일·Sol 100/일, 공식 리더보드 접수 개방과 본선 진출 10팀을 반영했다. 10월 13일 크레딧·횟수 복구는 그 날짜의 운영 조치이며 현재 계정 잔액으로 해석하지 않는다.

[10월 12일 비교](CHANGES_2026-10-12.md), [10월 6일 개회식](slides/opening-2026-10-06.md), [10월 11일 실행 흐름](slides/workflow-2026-10-11.md)은 당시 자료다. SDK 기록은 15개 SOAP 필드와 별도 주진단을 유지한다. 새 요청 대기·복구 가이드는 후속 구현 항목으로 기록했으며 이번 갱신에서 SDK를 바꾸거나 실제 호출하지 않았다. 선택과 문서 갱신 범위는 D01·D12, 실행 준비는 [제출 상태](../../submission/PROJECT_STATE.md), 출처·임상 검토는 [데이터 상태](../../data/PROJECT_STATE.md)가 소유한다.
