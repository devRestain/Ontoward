# 개발 도구

제출 전 작업과 검증을 관리한다. 실행 에이전트는 submission/, 지속 준비 결과는 data/, 임시 실행 증거는 Tmp/에 둔다.

| 경로 | 현재 역할 |
|---|---|
| [ontology/](ontology/README.md) | SNOMED CT·BODHI-S의 결정론적 v5.0 투영 |
| tests/workflow/ | 합성 SDK를 사용하는 전체 상담 행동 검증 |
| tests/ontology/ | 실제 원천 preview·해시·제외 사유·점수 검증 |
| [architecture/WORKFLOW_RULES.md](architecture/WORKFLOW_RULES.md) | 실행 규칙·소유 객체·행동 테스트 색인 |
| packaging/ | submission/만 읽는 독립 ZIP 구성 |
| codex/ | 보존된 준비 이미지와 기존 CLI 인증 설정 |

v5.0 준비는 Codex·NOVA 모델을 호출하지 않는다. 기존 extraction 이미지와 인증 volume은 보존하지만 현재 데이터 구축에 로그인이나 live 호출이 필요하지 않다. 호스트에 의존성을 설치하지 않고 프로젝트 Docker의 기존 Pydantic·RDFLib 환경을 사용한다.

프로젝트 루트에서 전체 흐름을 확인하거나 ZIP을 생성한다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/workflow/test_workflow.py
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml build --pull=false package
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never package
```

ZIP은 Tmp/packaging/ontoward-submission.zip에 만들어진다. 공개 설정·코드·정책·스키마와 별도 수용된 지식만 포함하고 Dev·data·원본·안내·상태·캐시·개발 키는 제외한다. 구성 검증과 임상 수용은 구분한다.

이전 v4.2 SNOMED·가이드라인 추출 도구는 deprecated 후 삭제했다. 과거 검토 영수증과 유용한 준비 결과는 [deprecation 목록](../data/ontology/deprecated.json)에 남기며 실행 경로로 사용하지 않는다. 현재 운영 사실은 [루트 상태](../PROJECT_STATE.md)에 기록한다.
