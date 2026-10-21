# 개발·검증 도구

새 DB 추출은 [Extraction/](../Extraction/README.md)이 소유한다. Dev/ontology·codex·guidelines와 점수/admission 전용 테스트는 D49에서 보관 후 활성 코드에서 철회했다. 과거 결과는 data/와 Tmp/에 보존하며 옛 builder를 새 실행의 fallback으로 쓰지 않는다.

| 경로 | 역할 |
|---|---|
| tests/workflow/ | 입력·세션·조건·질문·평가 고정·Education·SOAP·전송 유지 회귀 |
| tests/workflow/test_d49.py | qualitative effect·scope·부분/모순·Context·속성 존재 전제·첫 DD action |
| tests/workflow/test_d50.py | 정상 입력 형제 보존·동적 graph 자격·정확한 단답·호출 일정·공동 교육·순차 실행 |
| tests/workflow/test_d54.py | 모순 경로/부분 후보·관찰/취득 scope·세 교육 참조·어휘 통합·문서 안정 분할/projection·무손실 기대값 참조 |
| tests/workflow/audit_links.py | 현재 vocabulary 연결의 타입 위반 목록 생성; production prepare gate 변경 없음 |
| tests/workflow/fixture_bundle.py | Tmp/의 새 합성 번들 구성 |
| tests/workflow/test_admitted.py | 명시적 새 번들의 전체 상담·Education 경로 |
| packaging/package_submission.py | 필요한 runtime·공개 설정·참조 prompts/assets만 ZIP에 포함 |
| architecture/ | 과거 설계·리뷰 기록; 현재 활성 계약은 PRD·AGENTS를 우선 |

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps dev python -B -m unittest discover -s Dev/tests/workflow -p 'test_*.py'
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps -e PYTHONPATH=/workspace/submission:/workspace/Extraction dev python -B -m unittest discover -s Extraction/tests -p 'test_*.py'
```

검증은 프로젝트 컨테이너에서 수행하고 호스트에 의존성을 설치하지 않는다. 합성 프로토콜 통과·실제 모델 의미·임상적 정확성·공식 평가는 구분한다. 독립 ZIP 원본 SDK 검증은 Test/compose.d49.yaml을 사용한다.

[아틀라스](../Test/atlas.html#evidence)는 검증 층위와 코드 탐색 경로를 안내합니다. [D50 provenance](../data/provenance/algorithm-d50-2026-10-20.json)의 과거 소스·독립 ZIP 169회귀와 SDK completed 기록을 현재 문서 작업의 새 테스트 실행으로 해석하지 않습니다. 실제 번들 설치 전 production prepare/패키징 실패와 Tmp/ 합성 수용을 분리합니다.

```sh
docker compose build package
docker compose run --rm -T package
```

manifest가 없으면 마지막 명령은 knowledge_bundle_not_installed로 실패한다. 현재 설치 번들의 loader/prepare 검증과 정식 ZIP 생성은 별도이며 이 작업은 Tmp/의 합성 ZIP만 검증했다. 합성 번들은 별도 읽기 전용 /submission mount와 Tmp/ 출력으로 검증하며 정식 경로에 설치하지 않는다. 운영 결과는 [루트 상태](../PROJECT_STATE.md), D54 입력 지표와 보존 근거는 [d50.5 증빙](../data/provenance/algorithm-d50-5-2026-10-21.json)을 따른다.
