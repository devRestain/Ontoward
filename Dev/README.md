# 개발 도구

제출 전 작업과 검증을 관리한다. 실행 에이전트는 submission/, 지속 준비 결과는 data/, 임시 실행 증거는 Tmp/에 둔다.

| 경로 | 현재 역할 |
|---|---|
| [ontology/](ontology/README.md) | 원천 전용 전체 클래스 추출·한국어 처리·증빙 |
| tests/workflow/ | 합성 SDK를 사용하는 전체 상담 행동 검증 |
| tests/ontology/ | 실제 원천 preview·해시·제외 사유·점수 검증 |
| [architecture/WORKFLOW_RULES.md](architecture/WORKFLOW_RULES.md) | 실행 규칙·소유 객체·행동 테스트 색인 |
| [architecture/NOVA_REVIEW_2026-10-15.md](architecture/NOVA_REVIEW_2026-10-15.md) | D15 분석 보고서 채택과 후속 검토 조건 |
| packaging/ | submission/만 읽는 독립 ZIP 구성 |
| codex/ | 보존된 준비 이미지와 기존 CLI 인증 설정 |

v5.0 준비는 전체 원천 SQLite 수집과 결정론적 투영이 기본이다. D18의 한국어 전체 작업은 고정 작업 집합과 계산된 호출 상한 안에서 ontology-extraction 서비스의 Codex CLI·gpt-6-luna와 기존 전용 인증 volume을 사용한다. 생성과 별도 자동 의미 대조를 순차 실행하고 실패 시 중단한다. 호스트에 의존성을 설치하지 않고 기존 프로젝트 Docker의 SQLite·Pydantic·RDFLib를 사용한다.

프로젝트 루트에서 전체 흐름을 확인하거나 ZIP을 생성한다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B -m unittest discover -s Dev/tests/workflow -p 'test_*.py'
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml build --pull=false package
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never package
```

ZIP은 Tmp/packaging/ontoward-submission.zip에 만들어진다. 공개 설정·코드·정책·스키마와 별도 수용된 지식만 포함하고 Dev·data·원본·안내·상태·캐시·개발 키는 제외한다. 구성 검증과 임상 수용은 구분한다.

유지 중인 상담 행동 검증과 실제 원천 후보·한국어 자산을 이용한 격리 상담을 구분한다. D18에서 이전 실행 배치를 철회했으므로 실제 prepare가 실패하는 상태를 빈 Graph나 자동 승인으로 우회하지 않는다. 한국어 준비·검증·재실행 명령은 [온톨로지 도구](ontology/README.md)에 있다.

D18에서 이전 v4.2·seed·임상 배치·번역·승인·지침 교육 초안과 임시 사본을 삭제했다. 원본 자료와 일반 상담 동작은 보존한다. D37로 대체된 고정 교육 발췌 도구와 해당 테스트는 제거했다. 현재 교육 원문 연결은 [guidelines/](guidelines/README.md), 진단 후 계획·한국어 안내와 행동 검증은 submission/workflow/와 tests/workflow/test_delivery.py가 담당한다. 현재 운영 사실은 [루트 상태](../PROJECT_STATE.md)에 기록한다.

D46은 Ear·Brain·Mouth의 통합 상담을 유지 회귀로 검사한다. test_brain.py는 그래프 근거·수용 순위·질문·freeze를, test_record.py는 typed 인구 정보·관찰·SOAP를, test_budget.py는 공식 턴과 마지막 판단·교육 예약을 검사한다. 원천 점수 차분은 ontology/contributions.py의 준비 기능으로 옮겼고 비교·프로토콜 Brain 대역·상세 관측은 Test가 소유한다. 이전 점수·가상 답변 알고리즘은 동결된 이전 산출물로만 비교한다.
