# SNOMED CT 준비 도구

이 도구는 허가된 International Edition RF2에서 먼저 일곱 객체 유형의 어휘 registry를 확장하고, 사람이 선택한 registry로 Disease–ClinicalPattern–ClinicalFeature preview를 만듭니다. 기존 510개 영어 어휘는 검색 seed이며 고정 상한이 아닙니다. 가이드라인 준비 결과는 보존하지만 이 경로가 기본입니다.

프로젝트 루트에서 `docker compose up -d ontology-extraction`으로 준비 컨테이너를 시작합니다. RF2는 `assets/snomed/`에 수동으로 배치하며 컨테이너에서는 읽기 전용입니다. 다음 예시의 `20260531`과 `rf2-release/`는 형식 예시이므로 실제 파일의 릴리스 날짜와 경로로 바꿉니다.

```sh
docker compose exec -T ontology-extraction python -m Dev.ontology.snomed import \
  --rf2 assets/snomed/rf2-release \
  --release-date 20260531 \
  --language-refset 900000000000509007 \
  --database data/preparation/snomed/ie-20260531/rf2.sqlite

docker compose exec -T ontology-extraction python -m Dev.ontology.snomed expand-vocabulary \
  --database data/preparation/snomed/ie-20260531/rf2.sqlite \
  --output data/preparation/snomed/ie-20260531/vocabulary-candidates.json

docker compose exec -T ontology-extraction python -m Dev.ontology.snomed extract \
  --database data/preparation/snomed/ie-20260531/rf2.sqlite \
  --stage vocabulary \
  --input data/preparation/snomed/ie-20260531/vocabulary-candidates.json \
  --output-dir data/preparation/snomed/ie-20260531/vocabulary-dry-run
```

`extract`는 dry-run이 기본입니다. Stage 1 응답은 모든 packet에 map, decompose, exclude 중 하나를 반환해야 합니다. `validate`로 전체 응답과 실제 RF2 출처를 확인한 뒤, 생성된 review JSON Schema에 맞는 사람 검토 기록을 작성해 `freeze-vocabulary`를 실행합니다. 선택된 registry만 Stage 2의 `project` 입력으로 사용할 수 있습니다.

`project`는 정확한 `due_to`, `associated_with`, 또는 질환·Target 계층 교집합 경로만 만듭니다. 질환 하위 유형, RF2 관계 ID·그룹, 계층 경로와 원천 명칭은 preparation 기록에 남습니다. `extract --stage projection` 응답을 `validate`한 다음 `export-preview`로 RDF를 작성할 수 있습니다. preview는 제출 지식이 아니며 `submission/`으로 복사되지 않습니다.

실제 NOVA 요청은 별도 실행에서만 `extract`에 `--live --max-calls N --daily-remaining N`을 함께 지정해 활성화합니다. `NOVA_DEV_KEY`와 `NOVA_API_BASE`는 컨테이너 환경에서 읽습니다. 두 단계는 KST 기준 100회 팀 한도를 공유하며 장부는 로컬 사용량만 알기 때문에 `daily-remaining`은 실행자가 확인해 선언해야 합니다. timeout·quota·검증 오류는 자동 재시도하지 않습니다. API 호출 전 packet·요청 ID를 저장하고 응답 원문을 검증 전에 보존합니다.

```sh
docker compose exec -T ontology-extraction python -m Dev.ontology.snomed verify
```

`verify`는 합성 RF2와 NOVA test double만 사용합니다. 실제 RF2 적재, API 요청, 임상 검토, 실제 커버리지 측정, 제출용 지식 수용은 수행하지 않습니다. JSON Schema와 release metadata는 `import`가 `data/preparation/snomed/<dataset>/` 아래에 생성합니다.
