# v5.0 원천 전용 온톨로지 생성

공급된 SNOMED CT International·Korean RF2 Snapshot과 BODHI-S 8개 CSV 전체를 SQLite에 보존한다. 공모전 어휘는 완전한 원천 표현과 그 의존 개념으로 선택한다. 14개 클래스의 원천 역할, 파생 규칙, 추출 수와 미해결 이유를 같은 빌드에서 기록한다. 원천에서 근거를 찾지 못한 진찰 방법·검사 계획·문진 계통 연결은 만들지 않는다.

| 코드 | 역할 |
|---|---|
| source_projection.py | build/export/admit와 한국어 작업 집합·실행 진입점 |
| database.py | 원천 파일·행·최신 컴포넌트·판단·승인 기록 |
| source_catalog.py | 클래스별 원천 역할과 정확한 원천 관계·의존 어휘 |
| findings.py | 신체진찰 방법·임상 Observable·관계 그룹 기반 소견과 속성 후보, 분과별 공백 |
| connections.py | D20 원천 기반 ROS·typed Context·필수 조건과 공모전 배치의 명시적 사용자 수용 |
| provenance.py·storage.py | 공유 근거 집합과 대용량 과거 JSON의 검증된 압축 보관 |
| v5.py | 공유 Pattern·타입 Feature·질환별 Association·조건부 기여 |
| korean.py·prompts/ | 고정 작업 집합, 한국어 명칭·임상 질문 생성과 별도 의미 대조 |
| codex_cli.py | 전용 Docker 인증 volume을 사용하는 단일 Codex CLI 호출 |
| model_normalization.py | 별도로 선택할 수 있는 제한된 원천 정규화 후보 처리 |
| admission.py | 빌드에 고정된 새 승인과 실행 자산 수용 |
| evidence.py | 원천 패키지·인증 정보를 제외한 생성 증빙 ZIP |

## 재실행 순서

D20의 연결 단계는 전체 원천을 재적재하지 않고 기존 원천 custody를 읽기 전용으로 공유한다. 아래 명령은 새 경로에 연결 그래프를 재생성하는 예시다. `--accept-competition`은 이 세션에서 사용자가 선택한 공모전 후보 수용을 명시하며, 이 옵션이 없으면 검토 양식만 생성하고 승인 영수증은 만들지 않는다. 한국어 생성은 실행하지 않는다.

```sh
docker compose -f compose.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev \
  python -B -m Dev.ontology.source_projection connections \
  --database data/preparation/v5/source-only-2026-10-16/findings-2026-10-16/ontology.sqlite3 \
  --output Tmp/connections-replay --accept-competition
```

수용한 배치는 `data/preparation/v5/competition-graph-2026-10-16/`에 둔다. `connection-evidence.json`은 새 연결의 원천 경로, `review-approved.json`은 build·후보·변환 정책 승인, `required-text-assets.json`은 별도 한국어 세션의 실제 의존 항목이다. 한국어 세션은 새 작업 집합과 예산을 고정하고 `text_assets.questions`, `text_assets.labels`, `text_assets.exam_requests`의 JSON 경로·SHA-256을 영수증에 연결한다. exam_requests는 승인된 ExamMethod ID에서 NFC 1–30자 요청문으로 가는 객체이며 수용 시 RDF의 examRequestText에 반영한다. 완전한 문구 수용 전 manifest는 graph_admitted_text_pending이다.

D23은 D22의 검증된 환자 행동을 `data/preparation/v5/runtime-text-2026-10-16/review-approved.json`에 고정해 수용했다. 원래 그래프 영수증·manifest와 D22 생성 증빙을 보존하고, `admission.admit(..., report_path=...)`로 새 결과를 별도 경로에 기록한다. 현재 manifest는 admitted이며 완전한 원천 기반 표현·매핑·문구는 추가 사용자·임상 승인 대기 없이 공모전에 사용할 수 있다. 불완전한 의미·단위·획득 경로는 기술적 제외로 유지한다. 실행 검증은 `Dev/tests/workflow/test_korean_admitted.py`가 현재 submission과 독립 추출 ZIP에 같은 한국어 경로를 적용한다.

프로젝트 루트에서 기존 프로젝트 이미지를 사용한다. 현재 결과는 `data/preparation/v5/source-only-2026-10-16/findings-2026-10-16/`에 둔다. 아래 재현 예시의 `replay/`는 아직 결과가 없는 새 출력 경로여야 한다. 공급된 원본 패키지가 필요하며 증빙 ZIP에는 원본을 넣지 않는다. 호스트에 의존성을 설치하지 않는다.

**현재 Codex CLI 작업은 사용자 요청으로 후속 우선순위에 있다.** 첫 CLI 시도는 `model_providers.openai` 재시도 설정이 예약된 내장 provider ID를 덮어쓴다는 설정 오류로 모델 응답 없이 중단했다. 아래 한국어 실행 명령은 현재 코드의 재현 명령이며 성공한 명령으로 표시하지 않는다. 후속 작업에서 지원되는 설정을 검증하고 새 코드·작업 집합·호출 예산을 고정해야 한다. 기존 실패 요청을 자동 재전송하지 않는다.

```sh
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev \
  python -B -m Dev.ontology.source_projection build \
  --international assets/snomed/SnomedCT_InternationalRF2_PRODUCTION_20260501T120000Z \
  --korean assets/snomed/SnomedCT_ManagedServiceKR_PRODUCTION_KR1000267_20260615T120000Z \
  --bodhi assets/bodhi/bodhi-s/csv \
  --output data/preparation/v5/source-only-2026-10-16/replay

docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev \
  python -B -m Dev.ontology.source_projection korean-freeze \
  --catalog data/preparation/v5/source-only-2026-10-16/replay/catalog \
  --output data/preparation/v5/source-only-2026-10-16/replay/korean-workset.json

docker compose run --rm -T --no-deps --pull never ontology-extraction \
  python -B -m Dev.ontology.source_projection korean \
  --workset data/preparation/v5/source-only-2026-10-16/replay/korean-workset.json \
  --output data/preparation/v5/source-only-2026-10-16/replay/korean
```

원천 빌드는 네트워크와 개발 키를 차단한다. 같은 입력·코드 해시의 원천 빌드만 `--resume`으로 재사용한다. 이번 작업은 검증된 빈 베이스의 원천 DB를 별도 작업 DB로 복제하여 적재를 재사용했으며, 베이스의 임상 테이블과 파일을 덮어쓰지 않는다.

D19는 원천 행을 다시 쓰지 않고 `inactive_rf2_rows` 읽기 전용 뷰로 비활성 최신 컴포넌트의 제외 상태를 조회한다. RF2 표현은 `source_expressions`에 한 번 저장하고 `dispositions.expression_id`에서 연결한다. `preview/sources.json`과 `catalog/audit.json`은 동일 빌드의 정본 SQLite·테이블·행 수·원천 해시를 가리킨다. 상세 판단은 SQLite의 `dispositions`, 원천 표현은 `source_expressions`, 질환 주장은 `source_assertions`와 `catalog_assertions`에서 조회한다.

한국어 실행은 `ontology-extraction` 서비스와 기존 프로젝트 전용 Codex 인증 volume을 사용한다. 모델은 `gpt-6-luna`, reasoning은 medium이며 웹 검색을 끈다. 생성과 별도 의미 대조 각각 최대 20항목을 순차 요청한다. 번역 작업 수 L, 질문 작업 수 Q의 호출 상한은 `2 × (ceil(L / 20) + ceil(Q / 20))`다. 이전 NOVA 준비 경로의 하루 100회 제한을 이 작업에 적용하지 않는다. 실패·불명·의미 대조 거부·전체 응답 검증 실패 때 즉시 중단하며 자동 재시도나 다음 날 자동 재개를 하지 않는다. 완료 요청의 신원과 응답을 보존한다.

## 원천과 한국어 의미

RF2는 최신 effectiveTime을 선택한 뒤 활성 여부를 적용하고 모듈 의존성과 동일 버전 충돌을 검증한다. 관계 ID·그룹·특성·경로·원천 행을 보존한다. BODHI의 specialty·influence·prerequisite 등 원래 관계를 검사 계획이나 무조건적인 질환 지지로 바꾸지 않는다. 필수 조건·단위·역할을 해결하지 못한 표현은 전체를 보류한다.

소견 후보는 BODHI 증상 루트 외에도 명시적인 청진·촉진·타진·시진 Finding method, 임상 Observable 해석, 형태와 부위, Sign 근거에서 찾는다. 명시적인 병력·검사 방법은 신체진찰 후보에서 제외한다. 방법이 확정된 소견과 획득 미확정 소견을 구분하고, 같은 SCTID의 보고·진찰 경로를 자동 가산하지 않는다. D19의 `source-findings.ttl` 전체는 원천 카탈로그에 보존한다. D20은 선택한 표현만 별도 그래프 전용 배치로 수용하고 문구 준비를 분리한다. 실제 진찰과 prepare에는 검토된 요청 문구 및 전체 검증을 그대로 요구한다.

FindingAttribute는 기존 조건 축 외에 공급된 ClinicalObservable 비교 차원을 보존한다. `Interprets`와 `Has interpretation`이 같은 그룹에서 각각 하나인 경우만 해석 값을 연결한다. 단위·척도·속성 종류·측정 기법·전제 조건은 Observable 모델 메타데이터이며 임의의 문진 축이나 수치 임계값으로 바꾸지 않는다. BODHI `characteristic`의 미해결 의미·동반 소견·수치 조건은 계속 보류한다. 범위 확대를 이유로 모두 Quality에 넣지 않는다.

`finding-coverage.json`은 BODHI의 모든 분과와 ClinicalObservable의 직접 하위 영역을 집계한다. 분과는 원래 `edges_treated_by`와 완전한 소견-질환 원천 주장만으로 연결한다. 범위 수치는 원천 후보와 연결 공백을 설명하며 분과별 임상 충분성을 뜻하지 않는다.

같은 SCTID의 활성 Korean RF2 명칭을 우선 사용하고 Description ID·원천 행·판본을 보존한다. 누락 명칭의 모델 결과는 `model_translation`이다. Pattern·Feature 등 구조 레코드 표시는 연결된 용어와 조건으로 결정론적으로 구성한다. 질환 이름과 구조 레코드는 직접 문진 비대상이며, 관찰 가능한 증상·속성·맥락에만 임상 질문을 연결한다. 모든 질문은 준비 단계와 Doctor 전달 단계에서 각각 NFC 1–30 Unicode code points를 검증한다. 길이를 맞추려고 절단하거나 필수 조건을 삭제하지 않는다.

별도 Codex 의미 대조는 자동 검사이며 독립 임상 검증이 아니다. 선택 어휘의 한국어 또는 필요한 질문이 미해결이면 전체 한국어 준비를 완료로 표시하지 않는다.

## 결과와 승인 경계

| 산출물 | 역할 |
|---|---|
| ontology.sqlite3 | 원천·최신 행·어휘·변환·주장·판단·승인 대장 |
| report.json | 전체 적재·질환 투영·보류 결과 |
| preview/ | 후보 RDF·원천 주장·타입 값·기여·미승인 검토 양식 |
| catalog/ | 14개 클래스·원천 관계 JSONL·한국어 원문 연결·범위 보고서·해시 |
| catalog/source-findings.ttl | 확장 소견·속성·방법·원천 질환 표현 후보; 실행 수용 전 검토용 |
| catalog/evidence.json | 원천 식별자와 공유 근거 집합 ID 사전 |
| catalog/finding-coverage.json·finding-bindings.json·observable-metadata.json | 분과·관찰 영역, 그룹별 속성 값, 단위·기법 등 원천 메타데이터 |
| korean-workset.json | 중복 제거된 전체 작업·입력·코드·프롬프트 해시와 호출 상한 |
| korean/ | 요청 신원·원응답·별도 의미 대조·완료 결과와 중단 사유 |
| generation-evidence.zip | 생성 코드·Docker 설정·의존성·규칙·재실행 명령·검증 증빙 |

깨끗한 베이스와 삭제 영수증은 [준비 결과](../../data/preparation/v5/source-only-2026-10-16/README.md)에서 확인한다. 새 빌드는 `preview_only`이며 삭제된 과거 승인·임상 배치·수동 seed를 재사용하지 않는다. `export --database PATH --output NEW_PATH`와 `admit --database PATH --review PATH` 인터페이스는 유지한다. D23의 공모전용 사용 승인을 정확한 빌드·매핑·한국어 자산의 새 영수증에 연결한 뒤 admit를 실행하며 추가 임상 결정을 요구하지 않는다.

한국어 작업은 `evidence_id/evidence_ids`로 카탈로그의 공유 근거를 참조한다. 질문에는 대상과 그 대상의 `hasAttribute` 연결 근거만 붙이며 Location 등 속성 전체의 근거를 복사하지 않는다. 같은 빌드의 식별된 preview는 정본 DB에서 재생성하므로 `interrupted-preview-*`가 자동 누적되지 않는다. 다른 빌드나 식별 불가 파일은 보존하고 새 출력 경로를 요구한다.

이전 `build/`의 큰 JSON은 `archives/<원래 SHA256>.json.gz`와 `storage-compaction.json`에 보존한다. 압축 해제한 바이트 수와 SHA256이 원래 값과 같아야 원본 파생 JSON을 제거한다. `gzip -dc archives/<SHA256>.json.gz > <원래 상대 경로>`로 복원한다. 과거 작업 집합의 해시는 그대로이며 새 한국어 실행으로 간주하지 않는다. DB·원본 assets·빈 베이스·실패 요청 대장은 유지한다. 이 기록은 파일 내용 크기이며 APFS 공유 블록을 고려한 실제 디스크 점유량은 측정하지 않는다.

## 검증과 증빙 생성

```sh
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/verify_reset.py --directory data/preparation/v5/source-only-2026-10-16
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/test_database.py
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/test_findings.py
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/verify_database.py data/preparation/v5/source-only-2026-10-16/findings-2026-10-16
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/verify_catalog.py --directory data/preparation/v5/source-only-2026-10-16/findings-2026-10-16
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/verify_findings.py --directory data/preparation/v5/source-only-2026-10-16/findings-2026-10-16
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/ontology/verify_storage.py --directory data/preparation/v5/source-only-2026-10-16/findings-2026-10-16
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/workflow/test_workflow.py
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B Dev/tests/workflow/test_admitted.py --submission /workspace/submission --candidate /workspace/data/preparation/v5/source-only-2026-10-16/findings-2026-10-16 --output /workspace/Tmp/d19-verification/candidate
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B -m Dev.ontology.storage --directory data/preparation/v5/source-only-2026-10-16/build
docker compose -f compose.yaml -f Dev/tests/ontology/compose.build.yaml -f Dev/tests/workflow/compose.offline.yaml run --rm -T --no-deps --pull never dev python -B -m Dev.ontology.evidence --directory data/preparation/v5/source-only-2026-10-16/findings-2026-10-16
```

`storage`는 과거 D18 `build/`의 식별된 대용량 JSON만 압축 보관한다. 새 작업 집합에는 `verify_findings.py`로 공유 근거·분과·영역·작업 집합을 검증한다. `test_findings.py`는 획득 역할·모호한 그룹·압축 손상 실패를 검사한다. CLI 실행 대장을 검사하는 `verify_korean.py`는 모델 실행을 재개한 뒤 사용한다.

실제 원천 검사, 합성 환자·스크립트 SDK 상담, 실제 준비 모델 호출, 독립 임상 검증, 운영 admission, 공식 제출은 각기 구분한다. 후보 상담은 전체 한국어 자산이 생성·의미 대조를 통과했을 때만 격리 주입하며 미완료면 `not_run`과 정확한 사유를 기록한다. 현재 실행 결과는 [루트 상태](../../PROJECT_STATE.md)와 [데이터 상태](../../data/PROJECT_STATE.md), 선택은 [D18](../../DECISION_STATE.md#D18)과 [D19](../../DECISION_STATE.md#D19)가 소유한다.
