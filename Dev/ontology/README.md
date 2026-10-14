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

## 근거 기반 2단계 준비

`workflow.py`는 자료 선별 기록 → 문단·목록·표와 보조 문맥 → 원자적 영어 문장 → 기존 후보 구조 → 사용자 후보 검토 순서를 지원한다. 별도 에이전트 원문 의미 감사는 후보 수용 단계에 포함하지 않는다. 실제 모델 호출과 비교 실험은 별도로 입력 목록·호출 한도를 정한 뒤 수행한다.

먼저 사람이 `data/ontology/source-selection.schema.json`에 맞춰 선정 JSON을 작성한다. 카탈로그 유형은 `질환 개요(교과서)` 또는 `진료지침`이어야 하며, 승인된 Disease 중심 문서나 독립 장의 범위를 선택한다. 문서·해시·줄 범위·주제 근거 인용·검토자·선정 이유·대상 인구·판본·변환 품질·이용 조건 검토를 기록한다. 제공되지 않은 판본은 null로 둔다. 제목의 질환명만으로 자동 선정하지 않는다.

현재 선정 형식은 `topic_diseases` 배열과 `group_context`를 사용한다. 단일 질환 문서는 배열에 한 질환을 두고 그룹 문맥은 null로 지정한다. 여러 질환을 함께 다루는 문서는 승인된 질환들을 배열에 넣으며, 공유 질환군 주어를 해석하려면 `group_context`에 `source_term`, `member_diseases`, 정의의 원문 인용과 줄 범위를 담은 `evidence`를 기록한다. 구성 질환은 검토한 주제 목록 안에 있어야 한다.

그룹 정의는 `GROUP DEFINITION CONTEXT`로 본문·같은 절의 보조 문단과 구분하여 두 프롬프트에 제공한다. 공유 가능한 연관은 구성 질환마다 원자 문장·단일 Disease Pattern을 하나씩 만들고 본문과 정의를 모두 인용한다. 질환별 제한을 다른 구성원으로 넓히지 않으며 그룹 정의만으로 새 관계를 만들지 않는다. 문장·후보의 연결과 그룹 맥락은 검토 패킷에 남기고 최종 네 후보 배열이나 RDF 클래스에 그룹 필드를 추가하지 않는다. 이전 파일럿의 단일 `topic_disease` 입력은 당시 버전의 관측 자료로 보존하며 현재 형식의 실행 입력으로 자동 변환하지 않는다.

컨테이너 내부에서 쓰는 결과 경로는 `Tmp/codex/` 아래로 정한다. 아래 `UNIT_ID`는 `prepared.json`의 ready 단위 식별자로 바꾼다.

```sh
docker compose exec -T ontology-extraction python -m Dev.ontology.workflow prepare --selection Tmp/codex/my-extraction/selection.json --output Tmp/codex/my-extraction/prepared.json
docker compose exec -T ontology-extraction python -m Dev.ontology.workflow prompt-atomic --prepared Tmp/codex/my-extraction/prepared.json --unit UNIT_ID --output Tmp/codex/my-extraction/atomic-prompt.txt
docker compose exec -T ontology-extraction python -m Dev.ontology.workflow validate-atomic --prepared Tmp/codex/my-extraction/prepared.json --unit UNIT_ID --response Tmp/codex/my-extraction/atomic-response.json --output Tmp/codex/my-extraction/atomic-validated.json
docker compose exec -T ontology-extraction python -m Dev.ontology.workflow prompt-conversion --prepared Tmp/codex/my-extraction/prepared.json --unit UNIT_ID --atomic-response Tmp/codex/my-extraction/atomic-response.json --output Tmp/codex/my-extraction/conversion-prompt.txt
docker compose exec -T ontology-extraction python -m Dev.ontology.workflow validate-conversion --prepared Tmp/codex/my-extraction/prepared.json --unit UNIT_ID --atomic-response Tmp/codex/my-extraction/atomic-response.json --response Tmp/codex/my-extraction/conversion-response.json --output Tmp/codex/my-extraction/conversion-validated.json
```

각 프롬프트 생성 뒤의 모델 호출은 이 명령들에 포함되지 않는다. 첫 단계는 `data/ontology/atomic.schema.json`, 두 번째 단계는 `data/ontology/conversion.schema.json`을 출력 제약으로 사용한다. 원응답 파일을 그대로 보존하며 검증 실패 시 수정하거나 재시도하지 않는다. 두 번째 프롬프트는 첫 응답을 재검증하고 같은 원문·절 맥락을 다시 포함한다.

원자적 문장은 `claim_id`, `statement`, `relation_type`, `source_basis`, `concepts`, `evidence`를 가진다. 명시적인 증상·신체 소견 감별 목록은 `source_basis=differential`로 가능한 연관을 표현하고, 질환과 Target 두 개념만 기록한다. 최종 Pattern에는 Feature·기대 존재·중요도를 추가하지 않는다. 단독 질환명이나 질환 자체의 감별 목록으로 증상을 만들어내지 않는다.

두 번째 응답은 `candidates`, `links`, `excluded_claims`를 가진다. `candidates` 안의 네 배열은 기존 형식이며, 연결과 제외 기록은 제출 지식 밖에 둔다. 모든 후보와 원자적 문장을 빠짐없이 연결하거나 제외 이유로 설명해야 한다. 검증기는 연결된 개념·속성 값의 추가와 삭제, 근거 범위 이탈, 감별 관계의 Feature 추가를 거부한다. 최종 후보의 수용 여부는 사용자 검토로 결정한다.

## 같은 입력을 사용하는 직접 추출과 검토

`prompt-direct`와 `validate-direct`는 같은 `prepared.json`·`UNIT_ID`·CORE/CONTEXT와 지정된 그룹 정의를 사용한다. 직접 추출 응답은 기존 `data/ontology/extraction.schema.json`의 네 배열이며, 비교 시 문맥만에서 새 관계가 생성되지 않도록 동일한 CORE 근거 경계를 적용한다. 향후 비교에서는 동일한 임상 검토 기준의 정확도·재현율·조건 손실·단계별 누락과 토큰·처리 시간·사람의 검토 시간을 기록한다. 현재 도구 검증으로 모델 방식의 우열을 주장하지 않는다.

`conversion-validated.json`의 `review_items`에는 후보·원자적 문장·원문 근거가 함께 들어 있다. 사람은 `data/ontology/clinical-review.schema.json`에 맞춰 전체 검증 JSON을 `encode()` 형식으로 직렬화한 SHA-256, 검토자, 후보별 approved/rejected와 이유를 기록한다. 해시는 `workflow review-digest` 명령으로 얻는다.

```sh
docker compose exec -T ontology-extraction python -m Dev.ontology.workflow review-digest --validated Tmp/codex/my-extraction/conversion-validated.json
docker compose exec -T ontology-extraction python -m Dev.ontology.workflow review --prepared Tmp/codex/my-extraction/prepared.json --unit UNIT_ID --atomic-response Tmp/codex/my-extraction/atomic-response.json --response Tmp/codex/my-extraction/conversion-response.json --review Tmp/codex/my-extraction/review.json --output Tmp/codex/my-extraction/reviewed.json
```

`review`는 원본과 두 응답을 다시 검증하여 기록된 검토가 같은 전체 결과를 대상으로 하는지 확인한다. 한 후보라도 거부하면 전체 후보를 유지한 채 rejected로 기록한다. 빈 후보는 reviewed_empty이며, 실제 임상 검토 기록도 RDF·제출 수용을 자동 수행하지 않는다. 지속 준비 자료는 선정된 파일럿 계약에 따라 `data/preparation/`에 보존한다.

## 오프라인 확인과 스키마 생성

```sh
docker compose exec -T ontology-extraction python -m Dev.ontology.workflow_verify --output-dir Tmp/codex/my-workflow-check
docker compose exec -T ontology-extraction python -m Dev.ontology.workflow schemas --output-dir Tmp/codex/my-workflow-schemas
```

`schemas`가 만드는 선정·원자 문장·변환·임상 검토 네 JSON Schema는 Python 모델에서 생성한 뒤 data/ontology의 같은 파일명으로 복사한다. 기존 최종 `extraction.schema.json`은 변경하지 않는다. 검증 사례는 직접 작성한 후보·원문 근거와 합성 Markdown을 사용하며 실제 모델 성능이나 임상 전문가 검토 결과가 아니다.
