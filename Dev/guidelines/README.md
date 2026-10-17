# 질환과 가이드라인 자료실의 문서 매핑

현재 `submission/knowledge/manifest.json`에 수용된 모든 Disease를 제공 자료실의 관련 문서와 연결합니다. 준비 단계에서 문서와 출처를 찾으며, SOAP P 문장이나 환자별 치료 계획은 생성하지 않습니다. 기존 교육 초안이나 지식 수용을 재개하는 도구가 아닙니다.

`map.py`는 기존 RDF 검증·원문 절 파서와 읽기 전용 SQLite 접근을 재사용합니다. 추가 의존성이나 호스트 설치가 필요하지 않습니다. 카탈로그 허용 목록만 색인하며 제목·원문을 SQLite FTS5로 검색합니다. 질환 동의어는 현재 RDF와 같은 SCTID의 활성 SNOMED Description에서 가져옵니다.

```bash
# 원본·manifest·동의어·문서 해시를 고정하고 검색 후보를 준비합니다.
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev \
  python -B -m Dev.guidelines.map prepare --output data/preparation/guideline-mapping/NEW_BATCH

# 루트 .env의 NOVA_DEV_KEY를 사용합니다. 세션 밖 모델 요청은 개발 크레딧을 사용합니다.
docker compose run --rm --no-deps --pull never -T dev \
  python -B -m Dev.guidelines.map run --output data/preparation/guideline-mapping/NEW_BATCH \
  --max-calls 150 --batch-size 8

docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev \
  python -B -m Dev.guidelines.map export --output data/preparation/guideline-mapping/NEW_BATCH

docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev \
  python -B -m Dev.guidelines.map verify --output data/preparation/guideline-mapping/NEW_BATCH
```

새 배치 이름을 사용합니다. `prepare`는 기존 결과를 덮어쓰지 않습니다. 색인은 `Tmp/guideline-mapping/`에 두며, 정확한 경로는 새 배치의 `preparation.json`에 기록합니다.

모델은 NOVA의 `https://nova.snubhai.org/v1/chat/completions`에서 `openai/gpt-6-luna`를 사용합니다. 기본 대조는 추론 강도 low·최대 출력 6,000토큰이며, 최종 상세 대조는 medium을 사용합니다. 초기 크기 검증 요청도 보존합니다. 요청은 순차 처리하며 원본 후보를 줄인 전송용 문맥을 요청 파일에 그대로 보존합니다. 개별 요청을 70,000 UTF-8 바이트 이내로 묶고, 배치 시작 전에 필요한 요청 수를 계산합니다. 공급자 거절·불완전 응답·인용 검증 실패가 있으면 요청과 응답을 보존하고 멈춥니다. 이미 시도한 stage의 자동 재개나 동일 요청 자동 재전송은 하지 않습니다. 모델·대상·요청 상한·KST 날짜는 첫 실행에 고정하며, 수정한 코드와 프롬프트는 해시별로 보존합니다.

모델은 본문 근거의 `evidence_id`를 선택하고, 코드는 그 ID에 해당하는 원문 창을 정확히 복사합니다. 문서 제목을 본문 인용으로 바꾸거나 모델이 작성한 인용을 원문으로 간주하지 않습니다.

`--stage`와 `--candidates-file`은 같은 새 배치 안에서 명시적으로 분리한 작업 집합에 사용합니다. 이미 성공한 질환을 다시 포함하면 내보내기가 중복을 거절합니다. 문서가 선택되지 않았거나 처리되지 않은 질환만 더 넓게 검색하려면 다음 명령으로 한 번의 별도 복구 작업 집합을 만듭니다. 새 작업도 원래 요청 상한 안에 포함됩니다.

```bash
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev \
  python -B -m Dev.guidelines.map recover --output data/preparation/guideline-mapping/NEW_BATCH

docker compose run --rm --no-deps --pull never -T dev \
  python -B -m Dev.guidelines.map run --output data/preparation/guideline-mapping/NEW_BATCH \
  --max-calls 150 --batch-size 8 --stage recovery --candidates-file recovery-candidates.jsonl
```

결과는 다음 파일로 읽습니다.

| 파일 | 용도 |
|---|---|
| `inventory.json` | 고정된 질환·출처 동의어와 원천 행·카탈로그·모든 문서 해시·기존 제출 파일 해시 |
| `candidates.jsonl` | 전체 검색 후보와 원문 위치, 모델 호출 전 준비 기록 |
| `requests.jsonl`, `calls/`, `replay/` | 요청 예약·성공 응답 해시, 실제 전송 내용·응답·실패, 사용 코드와 프롬프트 |
| `mappings.csv` | 질환–문서 연결 한 행씩, 정렬·검색·검토용 |
| `mappings.json` | 질환별 구조화 결과, 원문 인용 위치, 전체 절 범위와 해시 |
| `review.md` | 원문 링크가 있는 질환별 탐색 문서 |
| `summary.json`, `verification.json` | 연결 범위와 수행한 재생 검증 결과 |

`relation`은 `exact`(동일 질환), `broader`(더 넓은 질환군), `narrower`(일부 하위 질환), `related`(관련 주제)를 구분합니다. 예를 들어 넓은 담도 질환에 담도 감염 지침을 연결한 결과는 일부 하위 범위이며, 모든 담도 질환의 항생제 치료를 지지하지 않습니다. 각 연결의 `scope`를 함께 읽어야 합니다.

미연결 복구에서는 보존된 SNOMED의 활성 Clinical finding 계층과 원문 제목에 대응하는 명칭을 사용해 상위·하위 주제를 찾습니다. `source_family_links`는 정확한 inferred is-a 관계 ID 경로와 명칭의 원천 행을 보존하며, 대상 Disease 목록에 새 질환을 추가하지 않습니다. 단복수·어순·접두어 검색은 문서 탐색에만 사용하며 질환 동의어를 생성하지 않습니다. 요청에 공급한 문서는 하나의 공유 풀로 대조하며, 근거 ID는 해당 요청 안에서 원문 창을 유일하게 식별합니다. 어떤 질환에도 공급하지 않은 문서나 근거는 거절합니다.

추가 복구는 `recover --recovery-round N`으로 새 `recovery-N-candidates.jsonl`을 만든 뒤 같은 이름의 `--stage recovery-N`으로 실행합니다. 모든 단계가 처음 고정한 요청 상한을 공유합니다. 성공한 연결은 다시 생성하지 않습니다. 상세 대조에서는 후보 문서와 원문 창을 늘리며, 입력 크기에 맞춰 배치를 줄입니다.

`document_role`은 모델이 읽은 문맥에서 판단한 실제 문서 역할입니다. 정식 지침, 교과서, 근거 리뷰, 환자 자료, 임상 요약을 구분하고 원래 카탈로그 유형도 보존합니다. 원문 인용 검증은 정확한 문자열과 출처 일치를 증명하며, 임상적 판단의 독립 검증을 대신하지 않습니다.

`evidence_use=care_navigation`은 관리 근거를 찾는 탐색 연결입니다. 실제 관리 내용 없이 임상 배경이나 감별 문맥만 확인된 경우에는 `background_only`로 표시하고 `plan_fields`와 `plan_sections`를 비웁니다. 배경 문서 연결을 P 근거 확보로 집계하지 않습니다. `summary.json`의 `background_only_diseases`가 해당 공백을 보존합니다.

`plan_sections`의 `candidate_fields`는 SOAP P의 `tests`, `treatment`, `disposition`, `follow_up`, `education`을 찾는 제목 기반 탐색 위치입니다. 절은 하위 제목·예외·조건을 포함한 전체 범위를 참조합니다. 절 제목이 해당 단어를 포함한다는 이유만으로 권고가 존재하거나 그 질환에 적용 가능하다고 간주하지 않습니다. 후속 추출에서는 원문 전체 절과 인구집단·중증도·진료 환경·금기·조건을 확인해야 합니다.

검증은 API를 호출하지 않습니다. 전 문서·기존 제출 런타임 파일의 해시, 질환 집합, 정확한 인용, 절 해시, 저장된 모델 응답과 결과 파일을 다시 대조합니다. 설명·운영 문서의 별도 변경은 목록으로 기록하며 덮어쓰지 않습니다. 기본 검증은 질환 하나라도 문서가 없으면 실패합니다. `--allow-gaps`는 진행 중 결과의 기술 검증에만 사용하며 전체 매핑 완료를 의미하지 않습니다. 원본 문서의 라이선스를 보존하고, 매핑 결과를 제출용 변형 문서나 재배포 허가로 취급하지 않습니다.

```bash
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev \
  python -B -m unittest Dev.tests.guidelines.test_mapping
```

## D37 런타임 문서 연결 내보내기

완료·검증된 D30 매핑을 현재 그래프 build에 연결한 인덱스로 내보낸다. 이 명령은 모델을 호출하지 않으며 원문과 기존 RDF·문진 자산을 보존한다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm --no-deps --pull never -T dev python -B -m Dev.guidelines.map runtime-export --output data/preparation/guideline-mapping/runtime843-2026-10-17
```

결과는 submission/knowledge/guideline-index.json, manifest의 해시 연결, data/preparation/guideline-runtime/education-2026-10-17/admission.json이다. 가이드라인 원문은 ZIP에 넣지 않고 NOVA_GUIDELINES_DIR 기본 /opt/nova/guidelines 아래에서 상대 경로와 해시로 확인한다. 진단 후 증례별 계획·한국어 안내는 D37 런타임이 소유하며 D30의 준비 검증이나 문서 연결이 임상 품질 검증을 대신하지 않는다.
