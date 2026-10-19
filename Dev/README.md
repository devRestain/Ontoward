# 개발·검증 도구

새 DB 추출은 [Extraction/](../Extraction/README.md)이 소유한다. Dev/ontology·codex·guidelines와 점수/admission 전용 테스트는 D49에서 보관 후 활성 코드에서 철회했다. 과거 결과는 data/와 Tmp/에 보존하며 옛 builder를 새 실행의 fallback으로 쓰지 않는다.

| 경로 | 역할 |
|---|---|
| tests/workflow/ | 입력·세션·조건·질문·평가 고정·Education·SOAP·전송 유지 회귀 |
| tests/workflow/test_d49.py | qualitative effect·scope·부분/모순·Context·속성 존재 전제·첫 DD action |
| tests/workflow/fixture_bundle.py | Tmp/의 새 합성 번들 구성 |
| tests/workflow/test_admitted.py | 명시적 새 번들의 전체 상담·Education 경로 |
| packaging/package_submission.py | 필요한 runtime·공개 설정·참조 prompts/assets만 ZIP에 포함 |
| architecture/ | 과거 설계·리뷰 기록; 현재 활성 계약은 PRD·AGENTS를 우선 |

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps dev python -B -m unittest discover -s Dev/tests/workflow -p 'test_*.py'
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps -e PYTHONPATH=/workspace/submission:/workspace/Extraction dev python -B -m unittest discover -s Extraction/tests -p 'test_*.py'
```

검증은 프로젝트 컨테이너에서 수행하고 호스트에 의존성을 설치하지 않는다. 합성 프로토콜 통과·실제 모델 의미·임상적 정확성·공식 평가는 구분한다. 독립 ZIP 원본 SDK 검증은 Test/compose.d49.yaml을 사용한다.

```sh
docker compose build package
docker compose run --rm -T package
```

실제 새 manifest가 없는 현재 마지막 명령은 knowledge_bundle_not_installed로 실패한다. 실제 설치 이후에만 Tmp/packaging/ontoward-submission.zip을 만든다. 임시 합성 번들은 별도 읽기 전용 /submission mount와 Tmp/ 출력으로 검증하며 정식 경로에 설치하지 않는다. 운영 결과는 [루트 상태](../PROJECT_STATE.md), custody는 [D49 증빙](../data/provenance/algorithm-d49-2026-10-19.json)을 따른다.
