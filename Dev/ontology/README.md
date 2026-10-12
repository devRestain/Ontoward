# 온톨로지 추출 스키마 사용

이 도구는 승인된 510개 영어 용어로 제한하는 후보 JSON과 원문 근거를 검증한다. `models.py`가 Pydantic 모델을, `extraction_prompt.md`가 Luna용 영어 지침을 정의한다. 생성된 어휘와 JSON Schema는 `data/ontology/`가 소유한다. 실제 모델 호출·배치 실행·Turtle 생성기는 포함하지 않는다.

모든 Python 명령은 프로젝트 루트에서 전용 컨테이너를 통해 실행한다. 호스트에 의존성을 설치하지 않는다.

```sh
docker compose build ontology-extraction
docker compose up -d ontology-extraction
docker compose exec -T ontology-extraction python -m Dev.ontology.verify
```

검증은 현재 승인 문서·기계용 어휘·입력 해시와 두 원본 문서를 사용하는 오프라인 사례를 비교한다. 결과는 `Tmp/codex/schema-check/verification.json`에 기록하며 검증 입력을 임시 파일에 의존하지 않는다. 임상 전문가 검토와 모델 품질 검증은 별도다.

스키마를 재생성하려면 현재 기계용 어휘를 기준으로 임시 산출물을 만든다. ontology mount는 읽기 전용이므로 검토한 임시 파일을 호스트의 프로젝트 디렉터리에서 원래 위치로 복사한다.

```sh
docker compose exec -T ontology-extraction python -m Dev.ontology.tools vocabulary --baseline data/ontology/extraction-vocabulary.json --output Tmp/codex/schema-check/extraction-vocabulary.json
cp Tmp/codex/schema-check/extraction-vocabulary.json data/ontology/extraction-vocabulary.json
docker compose exec -T ontology-extraction python -m Dev.ontology.tools schema --output Tmp/codex/schema-check/extraction.schema.json
cp Tmp/codex/schema-check/extraction.schema.json data/ontology/extraction.schema.json
```

프롬프트와 응답 검증은 다음 입력을 요구한다.

| 인자 | 의미 |
|---|---|
| `--document` | `assets/guidelines/` 기준 카탈로그 상대 경로 |
| `--sha256` | 지정 원본 파일 바이트의 SHA-256 |
| `--start-line`, `--end-line` | 원본 Markdown의 1부터 시작하는 포함 범위 |
| `--output` | 컨테이너에서 쓸 수 있는 `Tmp/codex/` 아래 결과 경로 |
| `--response` | `validate` 명령에서 읽을 응답 JSON |

`python -m Dev.ontology.tools prompt`는 원본 줄 번호와 절 맥락을 붙인 영어 프롬프트를 만든다. `validate`는 응답 전체를 엄격한 모델로 읽고 모든 인용을 확인한다. 실패 시 종료 코드 2를 반환하고 새 성공 산출물을 쓰지 않는다. 기존 결과 파일을 실패한 새 실행의 결과로 오인하지 않도록 입력별 결과 경로를 구분한다.

후속 파일럿에서 사용할 에이전트 전달물은 `data/ontology/extraction.schema.json`, 생성된 프롬프트와 원본 입력 식별 정보다. Codex CLI는 `--model gpt-6-luna`, `-c 'model_reasoning_effort="medium"'`, `--sandbox read-only`, `--output-schema`를 사용하고 기존 SNU Edu 인증·Standard 속도·웹 비활성화를 유지한다. 이 문서와 도구는 모델 호출을 시작하지 않는다.

출력은 `patterns`, `supporting_contexts`, `finding_methods`, `planned_tests` 네 배열이다. Feature는 부모 Pattern의 Target을 상속한다. 모든 관계와 Feature에는 정확한 원문 인용이 필요하다. 새로운 대상·속성·승인 값 조합도 후보로 표현할 수 있지만 `candidate_validated`는 형식·어휘·인용 통과를 의미한다. 인용된 문장이 임상 주장을 실제로 뒷받침하는지, 동의어 대응과 필수 조건이 보존됐는지, 라이선스와 RDF 수용이 가능한지는 별도로 검토한다. 미승인·미표현 항목의 보류 목록은 생성하지 않는다.
