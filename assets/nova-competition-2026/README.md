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

규칙·개발·평가·서비스 상태 페이지의 현재 확인일은 **2026년 10월 12일, 한국 시간**이다. 상태 페이지는 로그인 메일과 평가 실행기를 이용 가능으로 표시한다. 이는 실제 로그인이나 평가 성공의 증거가 아니다. 개발·제출 페이지의 로그인 전환과 공개 리더보드의 결과 부재는 10월 11일 관찰로 구분하며, 계정 내부 화면, 실제 키·크레딧·샘플 UUID, API 동작 여부는 확인하지 않았다. 일정과 운영 상태는 바뀔 수 있으므로 실행이나 제출 직전에 공식 페이지를 다시 확인해야 한다.

이 폴더는 프로젝트에서 새로 만든 공모전 참고 자료다. 원본 임상 자료, 검색 코퍼스, 제출물에 포함되는 자료와는 역할이 다르다. 제공 자료 자체의 구조는 [상위 Architecture.md](../Architecture.md), 프로젝트 요구사항과 결정은 [PRD](../../PRD.md)와 [DECISION_STATE](../../DECISION_STATE.md)에서 확인할 수 있다.

원문은 [NOVA 공식 사이트](https://nova.snubhai.org/), [규칙](https://nova.snubhai.org/rules/), [개발 문서](https://nova.snubhai.org/docs/), [평가 안내](https://nova.snubhai.org/evaluation/)에 있다. 이 정리는 로그인, API 실행, 자료 다운로드, 업로드 또는 공식 평가를 수행한 기록이 아니다.

## 10월 12일 갱신과 발표 자료

현재 적용 규칙은 [변경 비교](CHANGES_2026-10-12.md)에서 확인한다. [10월 6일 개회식](slides/opening-2026-10-06.md)과 [10월 11일 실행 흐름](slides/workflow-2026-10-11.md)은 원본과 날짜를 보존한 변환 자료다. 발표의 20분 제한·진찰 거절 턴·본선 배점을 최신 확정 규칙으로 혼용하지 않는다. SDK 기록은 15개 SOAP 필드와 별도 주진단으로 통일했다. 실제 프로젝트 선택은 D12가 소유한다.
